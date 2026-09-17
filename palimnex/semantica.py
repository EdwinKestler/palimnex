"""Optional Semantica projection of Palimnex audit graphs.

This module never imports the Semantica package. Callers pass a duck-typed
graph/context, or wrap one with bind_semantica() after installing the extra.
Projected copies are untrusted historical residue. Automatic TTL must be off;
Palimnex remains the only forget authority. A locator never triggers a fetch.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .adapters import ADAPTER_API_VERSION, AdapterReceipt, AdapterRegistry, Derivative
from .audit import SCHEMA, graph_digest
from .durable import canonical_json, now_ms
from .locators import ResolvedSource, SourceLocator, SourceRange, SourceResolver
from .security import scan_bytes

ADAPTER_ID = "semantica"
KNOWN_STORES = ("graph", "memory", "vectors")
COMPLETE_STATUSES = frozenset({"erased", "not_found"})
FAILURE_STATUSES = frozenset({"unsupported", "failed"})
_EVENT_ID = re.compile(r"[0-9a-f]{32}")
_OBJECT_ID = re.compile(r"[a-zA-Z0-9._:-]{1,128}")


@runtime_checkable
class GraphStore(Protocol):
    """Minimal ContextGraph-compatible surface used by the projector."""

    def add_node(self, node_id: str, node_type: str, content: str | None = None, **properties: Any) -> Any: ...
    def add_edge(self, source_id: str, target_id: str, edge_type: str = "related_to", **properties: Any) -> Any: ...
    def has_node(self, node_id: str) -> bool: ...


def require_disabled_ttl(context: Any | None) -> None:
    if context is None:
        return
    if getattr(context, "retention_days", None) is not None:
        raise ValueError("Palimnex-governed projections require retention_days=None")


def _receipt_stores(receipt: Any) -> dict[str, Any]:
    stores = getattr(receipt, "stores", None)
    if stores is None and isinstance(receipt, Mapping):
        stores = receipt.get("stores")
    if not isinstance(stores, Mapping):
        raise ValueError("invalid erasure receipt")
    return dict(stores)


def sanitize_erasure_receipt(receipt: Any) -> dict[str, Any]:
    """Keep store statuses and identifiers; drop backend blobs and reasons."""
    entity_id = getattr(receipt, "entity_id", None)
    if entity_id is None and isinstance(receipt, Mapping):
        entity_id = receipt.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id:
        raise ValueError("invalid erasure receipt")
    stores = {
        name: {"status": str((info or {}).get("status", "not_configured"))}
        for name, info in sorted(_receipt_stores(receipt).items())
        if name in KNOWN_STORES
    }
    body = {
        "schema": "palimnex:adapter-erasure:v1",
        "entity_id": entity_id,
        "stores": stores,
        "forensic_erasure": False,
    }
    body["receipt_digest"] = hashlib.sha256(canonical_json(
        {key: value for key, value in body.items() if key != "receipt_digest"}
    )).hexdigest()
    return body


def interpret_erasure_receipt(receipt: Any, mandatory_stores: frozenset[str]) -> dict[str, Any]:
    """Fail closed: mandatory not_configured/unsupported/failed is an error.

    Optional stores may be not_configured. Any unsupported or failed store fails.
    """
    stores = _receipt_stores(receipt)
    for name in mandatory_stores:
        status = str((stores.get(name) or {}).get("status", "not_configured"))
        if status not in COMPLETE_STATUSES:
            raise ValueError(f"mandatory store {name} reported {status}")
    for name, info in stores.items():
        status = str((info or {}).get("status", "not_configured"))
        if status in FAILURE_STATUSES:
            raise ValueError(f"store {name} reported {status}")
    return sanitize_erasure_receipt(receipt)


@runtime_checkable
class ErasureRunner(Protocol):
    def erase_entity(self, entity_id: str, reason: str | None = None, **kwargs: Any) -> Any: ...


class FailClosedCoordinator:
    """Wrap a Semantica ErasureCoordinator so incomplete mandatory stores raise."""

    def __init__(self, runner: ErasureRunner, *, mandatory_stores: Sequence[str] = ("graph",)):
        stores = tuple(mandatory_stores)
        if not stores or any(name not in KNOWN_STORES for name in stores):
            raise ValueError("invalid mandatory store inventory")
        if not isinstance(runner, ErasureRunner):
            raise ValueError("unsupported erasure coordinator")
        self.runner = runner
        self.mandatory_stores = frozenset(stores)

    def erase_entity(self, entity_id: str, reason: str | None = None, **kwargs: Any) -> Any:
        receipt = self.runner.erase_entity(entity_id, reason=reason, **kwargs)
        interpret_erasure_receipt(receipt, self.mandatory_stores)
        return receipt


def bind_semantica(context: Any) -> Any:
    """Accept a caller-built Semantica AgentContext or ContextGraph.

    Construction stays with the caller so retention_days=None is explicit.
    This function does not import or install Semantica.
    """
    require_disabled_ttl(context)
    graph = getattr(context, "knowledge_graph", None) or context
    if not isinstance(graph, GraphStore):
        raise ValueError("Semantica graph must provide add_node, add_edge, and has_node")
    return graph


class SemanticaProjectionAdapter:
    """In-process index of projected audit-graph objects.

    When a coordinator is supplied, delete() is fail-closed across the declared
    mandatory stores. Local graph removal remains available for tests.
    """
    api_version = ADAPTER_API_VERSION
    adapter_id = ADAPTER_ID

    def __init__(self, store: GraphStore, *, project_id: str,
                 coordinator: ErasureRunner | None = None,
                 mandatory_stores: Sequence[str] = ("graph",)):
        if not isinstance(store, GraphStore):
            raise ValueError("unsupported Semantica graph store")
        stores = tuple(mandatory_stores)
        if not stores or any(name not in KNOWN_STORES for name in stores):
            raise ValueError("invalid mandatory store inventory")
        if coordinator is not None and not isinstance(coordinator, ErasureRunner):
            raise ValueError("unsupported erasure coordinator")
        self.store = store
        self.project_id = project_id
        self.coordinator = coordinator
        self.mandatory_stores = frozenset(stores)
        self._rows: dict[str, tuple[str, str, str, bytes]] = {}
        self._projection: dict[str, tuple[str, str, str, bytes]] = {}
        self._sanitized: dict[str, dict[str, Any]] = {}

    def put(self, object_id: str, event_id: str, payload: bytes, *, version: str) -> None:
        if not _OBJECT_ID.fullmatch(object_id) or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("invalid derivative identity")
        if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", version) or len(payload) > 1_000_000 or scan_bytes(payload):
            raise ValueError("invalid derivative version or payload")
        digest = hashlib.sha256(payload).hexdigest()
        row = (event_id, version, digest, payload)
        self._rows[object_id] = row
        self._projection[object_id] = row

    def payload(self, object_id: str) -> tuple[bytes, str]:
        row = self._rows.get(object_id) or self._projection.get(object_id)
        if row is None:
            raise ValueError("source unavailable or version/digest mismatch")
        return row[3], row[1]

    def enumerate_derivatives(self, event_ids: Sequence[str]) -> Sequence[Derivative]:
        wanted = set(event_ids)
        found = []
        for object_id, row in {**self._projection, **self._rows}.items():
            event_id, version, digest, _payload = row
            if event_id in wanted:
                found.append(Derivative(self.adapter_id, self.project_id, object_id, version, digest))
        return tuple(sorted(found, key=lambda item: item.object_id))

    def delete(self, derivative: Derivative) -> None:
        self._check(derivative)
        row = self._rows.get(derivative.object_id)
        if row is not None and row[2] != derivative.digest:
            raise ValueError("derivative payload changed")
        if row is not None and row[1] != derivative.version:
            raise ValueError("derivative version changed")
        if self.coordinator is not None:
            receipt = self.coordinator.erase_entity(
                derivative.object_id, reason="palimnex-governed")
            self._sanitized[derivative.object_id] = interpret_erasure_receipt(
                receipt, self.mandatory_stores)
        self._rows.pop(derivative.object_id, None)
        if self.store.has_node(derivative.object_id):
            self._remove_store_node(derivative.object_id)

    def commit_receipts(self, plan_digest: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", plan_digest) or not self._sanitized:
            raise ValueError("adapter receipts require an applied plan digest")
        receipts = []
        for object_id in sorted(self._sanitized):
            body = self._sanitized[object_id]
            receipts.append({
                "object_id": object_id,
                "receipt_digest": body["receipt_digest"],
                "store_statuses": {name: info["status"] for name, info in body["stores"].items()},
            })
        return {
            "plan_digest": plan_digest,
            "adapter_id": self.adapter_id,
            "receipts": receipts,
            "mandatory_stores": sorted(self.mandatory_stores),
            "forensic_erasure": False,
        }

    def invalidate_projection(self, derivative: Derivative) -> None:
        self._check(derivative)
        row = self._projection.get(derivative.object_id)
        if row is None or (row[1] == derivative.version and row[2] == derivative.digest):
            self._projection.pop(derivative.object_id, None)

    def verify_absent(self, derivative: Derivative) -> bool:
        self._check(derivative)
        if derivative.object_id in self._rows or derivative.object_id in self._projection:
            return False
        return self.store.has_node(derivative.object_id) is not True

    def produce_receipt(self, derivative: Derivative, plan_digest: str) -> AdapterReceipt:
        return AdapterReceipt(
            "palimnex:adapter-receipt:v1", self.adapter_id, self.project_id,
            derivative.object_id, plan_digest, self.verify_absent(derivative), now_ms())

    def _check(self, derivative: Derivative) -> None:
        if derivative.project_id != self.project_id or derivative.adapter_id != self.adapter_id:
            raise ValueError("derivative scope mismatch")

    def _remove_store_node(self, node_id: str) -> None:
        remover = getattr(self.store, "remove_node", None) or getattr(self.store, "purge_node", None)
        if not callable(remover):
            raise ValueError("graph store cannot remove nodes")
        remover(node_id)


class SemanticaResolver:
    """Resolve projected Semantica objects from the local adapter index only."""
    api_version = 1

    def __init__(self, adapter: SemanticaProjectionAdapter):
        self.adapter = adapter

    def resolve(self, source_id: str, version: str) -> ResolvedSource:
        payload, stored_version = self.adapter.payload(source_id)
        if stored_version != version:
            raise ValueError("source unavailable or version/digest mismatch")
        return ResolvedSource(payload, stored_version)


def semantica_locator(adapter: SemanticaProjectionAdapter, source_id: str) -> SourceLocator:
    payload, version = adapter.payload(source_id)
    bounds = SourceRange("bytes", 0, len(payload))
    return SourceLocator("semantica", source_id, version, bounds, hashlib.sha256(payload).hexdigest())


def project_audit_graph(
    graph: Mapping[str, Any],
    store: GraphStore,
    *,
    project_id: str,
    registry: AdapterRegistry | None = None,
    context: Any | None = None,
    adapter: SemanticaProjectionAdapter | None = None,
) -> dict[str, Any]:
    """Copy an audit graph into a Semantica-compatible store as untrusted residue."""
    require_disabled_ttl(context)
    if graph.get("schema") != SCHEMA or graph_digest(graph) != graph.get("graph_digest"):
        raise ValueError("invalid or tampered audit graph")
    if not isinstance(store, GraphStore):
        raise ValueError("unsupported Semantica graph store")
    version = str(graph["graph_digest"])
    if adapter is None and registry is not None:
        existing = registry.get(ADAPTER_ID)
        if existing is not None:
            if not isinstance(existing, SemanticaProjectionAdapter):
                raise ValueError("semantica adapter already registered")
            adapter = existing
    projector = adapter or SemanticaProjectionAdapter(store, project_id=project_id)
    if projector.project_id != project_id or projector.store is not store:
        raise ValueError("adapter project or store mismatch")
    if registry is not None and registry.get(ADAPTER_ID) is None:
        registry.register(projector)
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("audit graph nodes and edges are required")
    derived = 0
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise ValueError("invalid audit graph node")
        payload = canonical_json(node)
        properties = {
            "palimnex_schema": SCHEMA,
            "palimnex_graph_digest": version,
            "authority": "historical_only",
            "authorizes_actions": False,
            "kind": node.get("kind"),
        }
        store.add_node(
            node["id"],
            f"palimnex:{node.get('kind', 'node')}",
            content=node["id"],
            valid_until=None,
            **properties,
        )
        event_id = node.get("event_id")
        if isinstance(event_id, str) and _EVENT_ID.fullmatch(event_id):
            projector.put(node["id"], event_id, payload, version=version)
            derived += 1
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("invalid audit graph edge")
        store.add_edge(str(edge["from"]), str(edge["to"]), str(edge["kind"]),
                       palimnex_graph_digest=version, authorizes_actions=False)
    return {
        "status": "projected",
        "adapter_id": ADAPTER_ID,
        "graph_digest": version,
        "nodes": len(nodes),
        "edges": len(edges),
        "derivatives": derived,
        "authority": "historical_only",
        "authorizes_actions": False,
        "retention_days": None,
    }
