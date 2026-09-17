from __future__ import annotations

import json
import unittest
from dataclasses import dataclass

from palimnex import Evidence, Event, Palimnex
from palimnex.adapters import AdapterRegistry
from palimnex.locators import resolve_locator
from palimnex.semantica import (
    FailClosedCoordinator,
    SemanticaProjectionAdapter,
    SemanticaResolver,
    bind_semantica,
    interpret_erasure_receipt,
    project_audit_graph,
    require_disabled_ttl,
    sanitize_erasure_receipt,
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


@dataclass
class FakeReceipt:
    entity_id: str
    stores: dict


class FakeCoordinator:
    def __init__(self, store: FakeGraph, statuses: dict[str, dict[str, str]]) -> None:
        self.store = store
        self.statuses = statuses
        self.calls: list[str] = []

    def erase_entity(self, entity_id: str, reason: str | None = None, **_kwargs: object) -> FakeReceipt:
        self.calls.append(entity_id)
        if self.statuses.get("graph", {}).get("status") in {"erased", "not_found"}:
            self.store.remove_node(entity_id)
        return FakeReceipt(entity_id, self.statuses)


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

    def test_fail_closed_mandatory_not_configured_and_unsupported(self) -> None:
        adapter = SemanticaProjectionAdapter(
            self.store, project_id=PROJECT_ID,
            coordinator=FakeCoordinator(self.store, {"graph": {"status": "not_configured"},
                                                     "vectors": {"status": "not_configured"}}),
            mandatory_stores=("graph",))
        project_audit_graph(self.graph, self.store, project_id=PROJECT_ID,
                            registry=self.registry, adapter=adapter)
        event_node = next(node for node in self.graph["nodes"] if node["kind"] == "event")
        plan = self.registry.plan("semantica", [event_node["event_id"]])
        with self.assertRaisesRegex(ValueError, "mandatory store graph reported not_configured"):
            self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)
        self.assertTrue(self.store.has_node(event_node["id"]))
        wrapped = FailClosedCoordinator(
            FakeCoordinator(self.store, {"graph": {"status": "unsupported"}}),
            mandatory_stores=("graph",))
        with self.assertRaisesRegex(ValueError, "mandatory store graph reported unsupported"):
            wrapped.erase_entity(event_node["id"])

    def test_optional_not_configured_is_allowed_failed_is_not(self) -> None:
        ok = interpret_erasure_receipt(
            FakeReceipt("event:x", {"graph": {"status": "erased"}, "vectors": {"status": "not_configured"}}),
            frozenset({"graph"}))
        self.assertEqual(ok["stores"]["graph"]["status"], "erased")
        self.assertNotIn("backend_result", json.dumps(ok))
        self.assertFalse(ok["forensic_erasure"])
        with self.assertRaisesRegex(ValueError, "store vectors reported failed"):
            interpret_erasure_receipt(
                FakeReceipt("event:x", {"graph": {"status": "erased"}, "vectors": {"status": "failed"}}),
                frozenset({"graph"}))
        sanitized = sanitize_erasure_receipt(FakeReceipt(
            "event:x", {"graph": {"status": "erased", "backend_result": {"raw": "secret-payload"}}}))
        self.assertNotIn("secret-payload", json.dumps(sanitized))
        self.assertNotIn("backend_result", sanitized["stores"]["graph"])

    def test_adapter_receipt_digest_lands_on_retention_chain(self) -> None:
        event = self.client.record(Event(
            self.sid, "fact", "cobalt orchard", {"state": "forget-me"},
            (Evidence("docs/alpha.md:1-3"),), retention="durable"))
        self.client.close_session(self.sid, "done")
        self.client.migrate_retention(expected_digest=self.client.status()["logical_digest"])
        self.client.activate_policy({"schema": "project-memory:retention-policy:v1", "policy_id": "test",
                                    "version": 1, "mode": "manual", "clock": "tx_at", "rules": [],
                                    "grace_after_close_seconds": 0, "plan_ttl_seconds": 3600},
                                   actor="tester", reason="test policy")
        self.client.authorize_erasure([event["event_id"]], authorized_by="tester",
                                      policy_id="test", reason_code="AUTHORIZED_ERASURE")
        local = self.client.plan_erasure([event["event_id"]])
        self.client.apply_erasure(local, confirm_digest=local["plan_digest"], key=b"f" * 32,
                                  actor="tester", reason="test erase")
        graph = self.client.audit_graph()
        adapter = SemanticaProjectionAdapter(
            self.store, project_id=PROJECT_ID,
            coordinator=FakeCoordinator(self.store, {"graph": {"status": "erased"},
                                                     "memory": {"status": "not_configured"}}),
            mandatory_stores=("graph",))
        project_audit_graph(graph, self.store, project_id=PROJECT_ID, registry=self.registry, adapter=adapter)
        tombstone = next(node for node in graph["nodes"] if node["kind"] == "tombstone")
        plan = self.registry.plan("semantica", [tombstone["event_id"]])
        self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)
        recorded = self.client.record_adapter_receipt(adapter.commit_receipts(local["plan_digest"]))
        self.assertFalse(recorded["forensic_erasure"])
        exported = self.client.audit_graph()
        action = next(node for node in exported["nodes"]
                      if node.get("control_kind") == "adapter_receipt")
        self.assertEqual(len(action["receipt_digest"]), 64)
        self.assertNotIn("forget-me", json.dumps(exported))
        self.assertNotIn("secret-payload", json.dumps(exported))


if __name__ == "__main__":
    unittest.main()
