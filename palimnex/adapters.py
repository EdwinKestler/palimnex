"""Versioned derivative adapter protocol and logical SQLite reference backend.

Adapters are trusted application code, registered explicitly. This coordinator
does not alter the retention ledger's holds, authorizations or pack blockers.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import asdict, dataclass
from typing import Callable, Protocol, Sequence, runtime_checkable

from .durable import canonical_json, now_ms
from .security import scan_bytes

ADAPTER_API_VERSION = 1


@dataclass(frozen=True)
class Derivative:
    adapter_id: str
    project_id: str
    object_id: str
    version: str
    digest: str


@dataclass(frozen=True)
class AdapterReceipt:
    schema: str
    adapter_id: str
    project_id: str
    object_id: str
    plan_digest: str
    verified_absent: bool
    verified_at: int
    scope: str = "logical-store-and-projection"


@runtime_checkable
class DerivativeAdapter(Protocol):
    api_version: int
    adapter_id: str
    project_id: str

    def enumerate_derivatives(self, event_ids: Sequence[str]) -> Sequence[Derivative]: ...
    def delete(self, derivative: Derivative) -> None: ...
    def verify_absent(self, derivative: Derivative) -> bool: ...
    def invalidate_projection(self, derivative: Derivative) -> None: ...
    def produce_receipt(self, derivative: Derivative, plan_digest: str) -> AdapterReceipt: ...


@dataclass(frozen=True)
class DerivativePlan:
    project_id: str
    adapter_id: str
    event_ids: tuple[str, ...]
    derivatives: tuple[Derivative, ...]
    expires_at: int

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json({"schema": "palimnex:derivative-plan:v1", **asdict(self)})).hexdigest()


class AdapterRegistry:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._adapters: dict[str, DerivativeAdapter] = {}

    def register(self, adapter: DerivativeAdapter) -> None:
        if not isinstance(adapter, DerivativeAdapter) or adapter.api_version != ADAPTER_API_VERSION:
            raise ValueError("unsupported derivative adapter protocol")
        if adapter.project_id != self.project_id or not re.fullmatch(r"[a-z0-9._-]{1,64}", adapter.adapter_id):
            raise ValueError("adapter project/identity mismatch")
        if adapter.adapter_id in self._adapters:
            raise ValueError("adapter already registered")
        self._adapters[adapter.adapter_id] = adapter

    def _enumerate(self, adapter: DerivativeAdapter, ids: Sequence[str]) -> tuple[Derivative, ...]:
        rows = adapter.enumerate_derivatives(ids)
        if len(rows) > 1000:
            raise ValueError("derivative limit exceeded")
        seen: set[str] = set()
        for ref in rows:
            if not isinstance(ref, Derivative) or ref.project_id != self.project_id or ref.adapter_id != adapter.adapter_id:
                raise ValueError("cross-project or cross-adapter derivative")
            if ref.object_id in seen or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", ref.object_id):
                raise ValueError("invalid or duplicate derivative identity")
            if not isinstance(ref.version, str) or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", ref.version):
                raise ValueError("invalid derivative version")
            if not isinstance(ref.digest, str) or not re.fullmatch(r"[0-9a-f]{64}", ref.digest):
                raise ValueError("invalid derivative digest")
            seen.add(ref.object_id)
        return tuple(sorted(rows, key=lambda ref: ref.object_id))

    def plan(self, adapter_id: str, event_ids: Sequence[str]) -> DerivativePlan:
        if isinstance(event_ids, str) or not 1 <= len(event_ids) <= 1000 or any(
            not isinstance(eid, str) or not re.fullmatch(r"[0-9a-f]{32}", eid) for eid in event_ids
        ):
            raise ValueError("expected bounded event IDs")
        adapter = self._adapters[adapter_id]
        ids = tuple(sorted(set(event_ids)))
        return DerivativePlan(self.project_id, adapter_id, ids,
                              self._enumerate(adapter, ids), now_ms() + 300_000)

    def apply(self, plan: DerivativePlan, *, confirm_digest: str,
              authorize: Callable[[DerivativePlan], bool]) -> tuple[AdapterReceipt, ...]:
        """Caller policy must verify current holds and authority for this scope.

        An adapter failure is raised; earlier deletions are not rolled back.
        Retry with the original plan is safe only for unchanged/absent objects.
        """
        if plan.project_id != self.project_id or plan.digest != confirm_digest or now_ms() > plan.expires_at:
            raise ValueError("invalid, changed or expired derivative plan")
        adapter = self._adapters[plan.adapter_id]
        current = self._enumerate(adapter, plan.event_ids)
        if any(ref not in plan.derivatives for ref in current):
            raise ValueError("derivatives changed; replan required")
        if any(ref not in current and adapter.verify_absent(ref) is not True for ref in plan.derivatives):
            raise ValueError("derivative is outside the enumerated scope")
        receipts = []
        for ref in plan.derivatives:
            if now_ms() > plan.expires_at:
                raise ValueError("derivative plan expired during execution")
            # Reevaluate application authority immediately before each deletion.
            if authorize(plan) is not True:
                raise PermissionError("current derivative erasure authority required")
            adapter.delete(ref)
            adapter.invalidate_projection(ref)
            if adapter.verify_absent(ref) is not True:
                raise ValueError("derivative absence verification failed")
            receipt = adapter.produce_receipt(ref, plan.digest)
            if (not isinstance(receipt, AdapterReceipt) or receipt.schema != "palimnex:adapter-receipt:v1"
                    or receipt.adapter_id != ref.adapter_id or receipt.project_id != ref.project_id
                    or receipt.object_id != ref.object_id or receipt.plan_digest != plan.digest
                    or receipt.verified_absent is not True or type(receipt.verified_at) is not int
                    or not 0 <= receipt.verified_at <= now_ms() or receipt.scope != "logical-store-and-projection"):
                raise ValueError("invalid adapter receipt")
            receipts.append(receipt)
        if self._enumerate(adapter, plan.event_ids):
            raise ValueError("new derivatives appeared during erasure; replan required")
        return tuple(receipts)


class SQLiteDerivativeAdapter:
    """Application-owned connection, separate from the Palimnex ledger.

    Initialization is explicit. Deletes cover rows in this namespace only, not
    database free pages, filesystem snapshots, backups or external replicas.
    Serialize access to the supplied connection at the application boundary.
    """
    api_version = ADAPTER_API_VERSION

    def __init__(self, connection: sqlite3.Connection, *, project_id: str,
                 adapter_id: str = "sqlite"):
        self.connection = connection
        self.project_id = project_id
        self.adapter_id = adapter_id

    def initialize(self) -> None:
        with self.connection:
            self.connection.execute("CREATE TABLE IF NOT EXISTS palimnex_derivatives ("
                                    "project TEXT, adapter TEXT, object TEXT, event TEXT, version TEXT, "
                                    "payload BLOB, digest TEXT, PRIMARY KEY(project,adapter,object))")
            self.connection.execute("CREATE TABLE IF NOT EXISTS palimnex_derivative_projection ("
                                    "project TEXT, adapter TEXT, object TEXT, event TEXT, version TEXT, "
                                    "payload BLOB, digest TEXT, "
                                    "PRIMARY KEY(project,adapter,object))")

    def put(self, object_id: str, event_id: str, payload: bytes, *, version: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", object_id) or not re.fullmatch(r"[0-9a-f]{32}", event_id):
            raise ValueError("invalid derivative identity")
        if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", version) or len(payload) > 1_000_000 or scan_bytes(payload):
            raise ValueError("invalid derivative version or payload")
        with self.connection:
            self.connection.execute("INSERT INTO palimnex_derivatives VALUES(?,?,?,?,?,?,?)",
                                    (*self._scope(object_id), event_id, version, payload, hashlib.sha256(payload).hexdigest()))
            self.connection.execute("INSERT INTO palimnex_derivative_projection VALUES(?,?,?,?,?,?,?)",
                                    (*self._scope(object_id), event_id, version, payload, hashlib.sha256(payload).hexdigest()))

    def _scope(self, object_id: str) -> tuple[str, str, str]:
        return self.project_id, self.adapter_id, object_id

    def _check(self, derivative: Derivative) -> None:
        if derivative.project_id != self.project_id or derivative.adapter_id != self.adapter_id:
            raise ValueError("derivative scope mismatch")

    def enumerate_derivatives(self, event_ids: Sequence[str]) -> Sequence[Derivative]:
        if not event_ids:
            return ()
        parameters = (self.project_id, self.adapter_id, *event_ids)
        selection = " WHERE project=? AND adapter=? AND event IN (" + ",".join("?" for _ in event_ids) + ")"
        # Projection-only survivors must remain discoverable after a partial
        # failure, including when the original operational plan was lost.
        rows = self.connection.execute(
            "SELECT object,version,digest,payload FROM palimnex_derivatives" + selection +
            " UNION SELECT object,version,digest,payload FROM palimnex_derivative_projection" + selection +
            " ORDER BY object LIMIT 1001", parameters + parameters).fetchall()
        if any(not isinstance(row[3], bytes) or hashlib.sha256(row[3]).hexdigest() != row[2] for row in rows):
            raise ValueError("derivative payload digest mismatch")
        return tuple(Derivative(self.adapter_id, self.project_id, *row[:3]) for row in rows)

    def delete(self, derivative: Derivative) -> None:
        self._check(derivative)
        with self.connection:
            if not self.connection.in_transaction:
                self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT payload FROM palimnex_derivatives WHERE project=? AND adapter=? AND object=?",
                self._scope(derivative.object_id)).fetchone()
            if row is not None and (not isinstance(row[0], bytes) or
                                    hashlib.sha256(row[0]).hexdigest() != derivative.digest):
                raise ValueError("derivative payload changed")
            # Compare and delete in one write transaction. Missing is idempotent.
            changed = self.connection.execute(
                "DELETE FROM palimnex_derivatives WHERE project=? AND adapter=? AND object=? AND version=? AND digest=?",
                (*self._scope(derivative.object_id), derivative.version, derivative.digest)).rowcount
            if not changed and self.connection.execute(
                "SELECT 1 FROM palimnex_derivatives WHERE project=? AND adapter=? AND object=?",
                self._scope(derivative.object_id)).fetchone():
                raise ValueError("derivative version changed")

    def invalidate_projection(self, derivative: Derivative) -> None:
        self._check(derivative)
        with self.connection:
            self.connection.execute(
                "DELETE FROM palimnex_derivative_projection WHERE project=? AND adapter=? AND object=? AND version=? AND digest=?",
                (*self._scope(derivative.object_id), derivative.version, derivative.digest))

    def verify_absent(self, derivative: Derivative) -> bool:
        self._check(derivative)
        return not any(self.connection.execute(
            f"SELECT 1 FROM {table} WHERE project=? AND adapter=? AND object=?",
            self._scope(derivative.object_id)).fetchone()
            for table in ("palimnex_derivatives", "palimnex_derivative_projection"))

    def produce_receipt(self, derivative: Derivative, plan_digest: str) -> AdapterReceipt:
        return AdapterReceipt("palimnex:adapter-receipt:v1", self.adapter_id, self.project_id,
                              derivative.object_id, plan_digest, self.verify_absent(derivative), now_ms())
