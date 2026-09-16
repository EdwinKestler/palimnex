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

    Graph mutations use the caller-supplied store. Delete/verify support local
    projection removal for tests; coordinated store erasure is slice C.
    """
    api_version = ADAPTER_API_VERSION
    adapter_id = ADAPTER_ID

    def __init__(self, store: GraphStore, *, project_id: str):
        if not isinstance(store, GraphStore):
            raise ValueError("unsupported Semantica graph store")
        self.store = store
        self.project_id = project_id
        self._rows: dict[str, tuple[str, str, str, bytes]] = {}
        self._projection: dict[str, tuple[str, str, str, bytes]] = {}

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
        self._rows.pop(derivative.object_id, None)
        self._remove_store_node(derivative.object_id)

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
