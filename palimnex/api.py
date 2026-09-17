"""Public SDK v1. Public methods are rooted explicitly and never create state on open."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from . import cache_v3, core, retention
from .durable import MemoryLedger
from .identity import Signer, TrustedIdentity
from .locators import SourceLocator, SourceResolver

API_VERSION = 1
EventKind = Literal["task", "decision", "failure", "outcome", "fact", "evidence", "correction", "revocation"]
Sensitivity = Literal["public", "internal", "restricted", "secret"]
Retention = Literal["volatile", "session", "durable"]


@dataclass(frozen=True)
class Evidence:
    locator: SourceLocator | str

    def to_record(self) -> dict[str, Any]:
        return {"kind": "source", "locator": self.locator.encode() if isinstance(self.locator, SourceLocator) else self.locator}


@dataclass(frozen=True)
class Event:
    session_id: str
    kind: EventKind
    subject: str
    payload: Any
    evidence: tuple[Evidence, ...] = ()
    sensitivity: Sensitivity = "internal"
    retention: Retention = "session"
    supersedes: str | None = None
    contradicts: str | None = None
    valid_from: int | None = None


@dataclass(frozen=True)
class RecallOptions:
    limit: int = 10
    known_at: int | None = None
    valid_at: int | None = None
    include_history: bool = False
    include_untrusted: bool = False
    max_sensitivity: Sensitivity = "internal"
    visibility: Literal["audit", "current"] = "audit"


class Palimnex:
    api_version = API_VERSION

    def __init__(self, root: Path | str, *, writable: bool = False,
                 source_resolvers: Mapping[str, SourceResolver] | None = None):
        self.root = Path(root).resolve(strict=True)
        if not (self.root / ".palimnex.json").is_file():
            raise ValueError("explicit repository configuration .palimnex.json is required")
        self.writable = writable
        self._ledger = retention.open_ledger(MemoryLedger(
            core.durable_ledger_path(self.root), project_id=cache_v3.project_id(self.root),
            project_slug=core.project_slug(self.root), root=self.root,
            source_resolvers=source_resolvers))

    def _require_write(self) -> None:
        if not self.writable:
            raise PermissionError("SDK client is read-only; explicit writable=True required")

    def initialize(self) -> dict[str, Any]:
        self._require_write()
        return self._ledger.initialize()

    def status(self) -> dict[str, Any]:
        return self._ledger.status()

    def start_session(self, task: str) -> dict[str, Any]:
        self._require_write()
        return self._ledger.start_session(task)

    def close_session(self, session_id: str, outcome: str) -> dict[str, Any]:
        self._require_write()
        return self._ledger.close_session(session_id, outcome=outcome)

    def record(self, event: Event) -> dict[str, Any]:
        self._require_write()
        return self._ledger.append_event(
            event.session_id, event.kind, subject=event.subject, payload=event.payload,
            evidence=[item.to_record() for item in event.evidence], sensitivity=event.sensitivity,
            retention=event.retention, supersedes=event.supersedes, contradicts=event.contradicts,
            valid_from=event.valid_from)

    def record_evidence(self, session_id: str, subject: str, locator: SourceLocator | str) -> dict[str, Any]:
        return self.record(Event(session_id, "evidence", subject,
                                 {"description": subject}, (Evidence(locator),)))

    def recall(self, query: str, options: RecallOptions | None = None) -> dict[str, Any]:
        options = options or RecallOptions()
        return self._ledger.recall(
            query, limit=options.limit, known_at=options.known_at, valid_at=options.valid_at,
            include_history=options.include_history, include_untrusted=options.include_untrusted,
            max_sensitivity=options.max_sensitivity, visibility=options.visibility)

    def reverify(self, event_id: str) -> dict[str, Any]:
        self._require_write()
        return self._ledger.reverify(event_id)

    def plan_erasure(self, event_ids: list[str] | None = None) -> dict[str, Any]:
        if isinstance(self._ledger, retention.RetentionLedger):
            return self._ledger.propose(event_ids=event_ids)
        return retention.unconfigured_plan(self._ledger)

    def verify_erasure(self, plan_digest: str) -> dict[str, Any]:
        if not isinstance(self._ledger, retention.RetentionLedger):
            return {"verified": False, "reason": "retention_migration_required"}
        with self._ledger.connection(create=False) as connection:
            state = self._ledger._state(connection)
            receipt = state["erased"].get(plan_digest)
            if receipt is None:
                return {"verified": False, "reason": "receipt_not_found"}
            # Opening validates tombstones and absence of reconstructive derivatives.
            return {"verified": plan_digest in state["compacted"], "receipt": receipt,
                    "scope": "local-ledger", "forensic_erasure": False,
                    "authority": "historical_only", "authorizes_actions": False}

    def migrate_retention(self, *, expected_digest: str) -> dict[str, Any]:
        self._require_write()
        result = retention.migrate(self._ledger, expected_digest=expected_digest)
        self._ledger = retention.open_ledger(self._ledger)
        return result

    def activate_policy(self, policy: dict[str, Any], *, actor: str, reason: str) -> dict[str, Any]:
        self._require_write()
        if not isinstance(self._ledger, retention.RetentionLedger):
            raise ValueError("retention migration required")
        return self._ledger.activate_policy(policy, actor=actor, reason=reason)

    def authorize_erasure(self, event_ids: list[str], *, authorized_by: str,
                         policy_id: str, reason_code: str) -> dict[str, Any]:
        self._require_write()
        if not isinstance(self._ledger, retention.RetentionLedger):
            raise ValueError("retention migration required")
        return self._ledger.authorize_erasure(event_ids, authorized_by=authorized_by,
                                              policy_id=policy_id, reason_code=reason_code)

    def apply_erasure(self, plan: dict[str, Any], *, confirm_digest: str,
                     key: bytes, actor: str, reason: str) -> dict[str, Any]:
        self._require_write()
        if not isinstance(self._ledger, retention.RetentionLedger):
            raise ValueError("retention migration required")
        return self._ledger.apply(plan, confirm_digest=confirm_digest, key=key, actor=actor, reason=reason)

    def record_adapter_receipt(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._require_write()
        if not isinstance(self._ledger, retention.RetentionLedger):
            raise ValueError("retention migration required")
        return self._ledger.record_adapter_receipt(dict(payload))

    def audit_graph(self, *, max_sensitivity: str = "restricted",
                    include_untrusted: bool = False,
                    checkpoint: Mapping[str, Any] | None = None,
                    signer: Signer | None = None) -> dict[str, Any]:
        from .audit import build_audit_graph
        return build_audit_graph(
            self._ledger, max_sensitivity=max_sensitivity, include_untrusted=include_untrusted,
            checkpoint=checkpoint, signer=signer)

    def export_audit_graph(self, output: Path, *, max_sensitivity: str = "restricted",
                           include_untrusted: bool = False,
                           checkpoint: Mapping[str, Any] | None = None,
                           signer: Signer | None = None) -> dict[str, Any]:
        from .audit import export_audit_graph
        self._require_write()
        return export_audit_graph(
            self._ledger, output, max_sensitivity=max_sensitivity,
            include_untrusted=include_untrusted, checkpoint=checkpoint, signer=signer)

    def checkpoint(self, *, commitment_key: bytes, signer: Signer,
                   previous: Mapping[str, Any] | None = None,
                   trusted: Mapping[str, TrustedIdentity] | None = None) -> dict[str, Any]:
        from .integrity import create_checkpoint
        return create_checkpoint(self._ledger, commitment_key=commitment_key, signer=signer,
                                 previous=previous, trusted=trusted)

    def verify_checkpoint(self, checkpoint: Mapping[str, Any], *, commitment_key: bytes,
                          trusted: Mapping[str, TrustedIdentity], expected_tip: str) -> dict[str, Any]:
        from .integrity import verify_current
        return verify_current(self._ledger, checkpoint, commitment_key=commitment_key,
                              trusted=trusted, expected_tip=expected_tip)

    def export_pack(self, output: Path, key: bytes, *, signer: Signer | None = None,
                    include_audit_graph: bool = False) -> dict[str, Any]:
        from .portable import export_pack
        self._require_write()
        return export_pack(self._ledger, output, key, signer=signer,
                           include_audit_graph=include_audit_graph)

    def import_pack(self, pack: Path, key: bytes, *, signature: dict[str, Any] | None = None,
                    trusted_signers: Mapping[str, TrustedIdentity] | None = None,
                    require_signature: bool = True, activate: bool = False,
                    replace: bool = False) -> dict[str, Any]:
        from .portable import import_pack
        # Existing import also performs intent recovery, even for quarantine.
        self._require_write()
        return import_pack(self._ledger, pack, key, signature=signature,
                           trusted_signers=trusted_signers, require_signature=require_signature,
                           activate=activate, replace=replace)
