from __future__ import annotations

import json
import unittest
from dataclasses import dataclass

from palimnex import Evidence, Event, Palimnex
from palimnex.adapters import AdapterRegistry
from palimnex.locators import resolve_locator
from palimnex.semantica import (
    SemanticaProjectionAdapter,
    SemanticaResolver,
    bind_semantica,
    project_audit_graph,
    require_disabled_ttl,
    semantica_locator,
)
from palimnex.tests.support import PROJECT_ID, write_project
from pathlib import Path
import tempfile


class FakeGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: list[tuple[str, str, str]] = []

    def add_node(self, node_id: str, node_type: str, content: str | None = None, **properties: object) -> bool:
        self.nodes[node_id] = {"type": node_type, "content": content, **properties}
        return True

    def add_edge(self, source_id: str, target_id: str, edge_type: str = "related_to", **_properties: object) -> bool:
        self.edges.append((source_id, target_id, edge_type))
        return True

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.edges = [edge for edge in self.edges if node_id not in edge[:2]]


@dataclass
class FakeContext:
    retention_days: int | None
    knowledge_graph: FakeGraph


class SemanticaProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_project(self.root)
        self.client = Palimnex(self.root, writable=True)
        self.client.initialize()
        self.sid = self.client.start_session("semantica projection")["session_id"]
        self.client.record(Event(
            self.sid, "fact", "cobalt orchard", {"state": "cobalt orchard"},
            (Evidence("docs/alpha.md:1-3"),), retention="durable"))
        self.graph = self.client.audit_graph()
        self.store = FakeGraph()
        self.registry = AdapterRegistry(PROJECT_ID)

    def test_ttl_must_be_disabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "retention_days=None"):
            require_disabled_ttl(FakeContext(30, self.store))
        require_disabled_ttl(FakeContext(None, self.store))
        with self.assertRaisesRegex(ValueError, "retention_days=None"):
            project_audit_graph(self.graph, self.store, project_id=PROJECT_ID,
                                context=FakeContext(30, self.store))

    def test_bind_semantica_uses_knowledge_graph_and_refuses_ttl(self) -> None:
        context = FakeContext(None, self.store)
        self.assertIs(bind_semantica(context), self.store)
        with self.assertRaises(ValueError):
            bind_semantica(FakeContext(7, self.store))
        with self.assertRaises(ValueError):
            bind_semantica(object())

    def test_project_copies_graph_as_untrusted_without_auto_expiry(self) -> None:
        report = project_audit_graph(
            self.graph, self.store, project_id=PROJECT_ID, registry=self.registry,
            context=FakeContext(None, self.store))
        self.assertEqual(report["status"], "projected")
        self.assertFalse(report["authorizes_actions"])
        self.assertIsNone(report["retention_days"])
        event_nodes = [node for node in self.graph["nodes"] if node["kind"] == "event"]
        self.assertTrue(event_nodes)
        projected = self.store.nodes[event_nodes[0]["id"]]
        self.assertEqual(projected["authority"], "historical_only")
        self.assertIs(projected["authorizes_actions"], False)
        self.assertIsNone(projected["valid_until"])
        self.assertTrue(any(edge[2] == "evidenced_by" for edge in self.store.edges))
        adapter = self.registry.get("semantica")
        assert isinstance(adapter, SemanticaProjectionAdapter)
        event_id = event_nodes[0]["event_id"]
        derived = {item.object_id for item in adapter.enumerate_derivatives([event_id])}
        self.assertIn(event_nodes[0]["id"], derived)

    def test_resolver_is_local_only_and_records_as_semantica_evidence(self) -> None:
        project_audit_graph(self.graph, self.store, project_id=PROJECT_ID, registry=self.registry)
        adapter = self.registry.get("semantica")
        assert isinstance(adapter, SemanticaProjectionAdapter)
        event_node = next(node for node in self.graph["nodes"] if node["kind"] == "event")
        locator = semantica_locator(adapter, event_node["id"])
        self.assertEqual(locator.scheme, "semantica")
        resolver = SemanticaResolver(adapter)
        raw = resolve_locator(locator, self.root, {"semantica": resolver})
        self.assertEqual(json.loads(raw.decode())["event_id"], event_node["event_id"])
        with self.assertRaises(ValueError):
            self.client.record_evidence(self.sid, "projected", locator)
        external = Palimnex(self.root, writable=True, source_resolvers={"semantica": resolver})
        recorded = external.record_evidence(self.sid, "projected entity", locator)
        self.assertTrue(recorded["verified"])

    def test_tampered_graph_and_reuse_of_registered_adapter(self) -> None:
        project_audit_graph(self.graph, self.store, project_id=PROJECT_ID, registry=self.registry)
        damaged = dict(self.graph)
        damaged["graph_digest"] = "0" * 64
        with self.assertRaises(ValueError):
            project_audit_graph(damaged, self.store, project_id=PROJECT_ID, registry=self.registry)
        again = project_audit_graph(self.graph, self.store, project_id=PROJECT_ID, registry=self.registry)
        self.assertEqual(again["graph_digest"], self.graph["graph_digest"])
        self.assertIsInstance(self.registry.get("semantica"), SemanticaProjectionAdapter)

    def test_projection_delete_removes_local_copy(self) -> None:
        project_audit_graph(self.graph, self.store, project_id=PROJECT_ID, registry=self.registry)
        adapter = self.registry.get("semantica")
        assert isinstance(adapter, SemanticaProjectionAdapter)
        event_node = next(node for node in self.graph["nodes"] if node["kind"] == "event")
        plan = self.registry.plan("semantica", [event_node["event_id"]])
        self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)
        self.assertFalse(self.store.has_node(event_node["id"]))
        self.assertTrue(adapter.verify_absent(plan.derivatives[0]))


if __name__ == "__main__":
    unittest.main()
