from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from palimnex import cache_v3
from palimnex._offline_fixtures import PROJECT_ID, write_project
from palimnex._offline_redis import FakeRedis
from palimnex.concepts import canonical_registry_digest
from palimnex.durable import canonical_json
from palimnex.experience import assemble_context
from palimnex.ontology_influence import (
    PROMOTION_EVIDENCE_SCHEMA,
    ActiveInfluence,
    InfluenceSetting,
    OntologyInfluenceError,
    activate_influence,
    influence_implementation_digest,
    read_influence_setting,
)
from palimnex.retrieval import retrieve_sources, shadow_retrieve


REGISTRY_PATH = "ontology/concept-registry.v1.json"
EVIDENCE_PATH = "artifacts/ontology/promotion-evidence.json"
STABLE_GOLDEN_ROOT = Path("/tmp/palimnex-influence-golden-corpus-v1")
GOLDEN_QUERIES = (
    "alpha service",
    "AlphaService",
    "build alpha",
    "beta client",
    "BetaClient",
    "gamma helper",
    "GammaHelper",
    "graph imports",
    "deployment guide",
    "configuration reference",
    "missing phrase",
    "service client helper",
)
RETRIEVAL_GOLDEN_SHA256 = (
    "228f4990c583e927c22859e10d7379852a658df609a7fdb5dcbd15bec94f0bad"
)
CONTEXT_GOLDEN_SHA256 = (
    "2fcea9ed3d9cdf7806f6d8053fe56ecf108198b89017614f6d22343f8803c8c8"
)


class RetrievalInfluenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_project(
            self.root,
            {
                "docs/a-target.md": "Unrelated target material.\n",
                "docs/z-popular.md": "Quasar quasar quasar lexical winner.\n",
                "docs/filler.md": "Bounded retrieval filler.\n",
            },
        )

    def write_config(self, influence: dict[str, Any] | None) -> None:
        path = self.root / ".palimnex.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document.pop("ontology_influence", None)
        if influence is not None:
            document["ontology_influence"] = influence
        path.write_text(
            json.dumps(document, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def binding(self, relative: str = "docs/a-target.md") -> dict[str, Any]:
        raw = (self.root / relative).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        return {
            "scheme": "repo",
            "source_id": relative,
            "version": digest,
            "range": {"unit": "bytes", "start": 0, "end": len(raw)},
            "digest": digest,
        }

    def concept(
        self,
        concept_id: str = "concept.quasar",
        *,
        alias: str = "quasar",
        relative: str = "docs/a-target.md",
    ) -> dict[str, Any]:
        return {
            "concept_id": concept_id,
            "canonical_name": concept_id.replace(".", " "),
            "aliases": [alias],
            "definition": "A bounded retrieval influence concept.",
            "source_bindings": [self.binding(relative)],
            "status": "approved",
            "provenance": {"origin": "manual"},
        }

    def registry_document(
        self, concepts: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": "palimnex:concept-registry:v1",
            "project": {
                "project_slug": "memory-fixture",
                "project_id": PROJECT_ID,
            },
            "registry_version": 1,
            "registry_kind": "approved_registry",
            "concepts": concepts or [self.concept()],
            "registry_digest": "0" * 64,
            "authority": "historical_only",
            "authorizes_actions": False,
        }
        document["registry_digest"] = canonical_registry_digest(document)
        return document

    def write_registry(self, document: dict[str, Any]) -> str:
        path = self.root / REGISTRY_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json(document))
        return str(document["registry_digest"])

    @staticmethod
    def metrics() -> dict[str, Any]:
        return {
            "case_count": 1,
            "cases_passed": 1,
            "critical_case_count": 1,
            "critical_pass_count": 1,
            "forbidden_path_hits": 0,
            "recall_at_limit": 1.0,
            "mrr": 1.0,
            "negative_abstention": 1.0,
            "negative_case_count": 0,
        }

    def promotion_document(self, registry_digest: str) -> dict[str, Any]:
        suite = {
            "baseline": self.metrics(),
            "influenced": self.metrics(),
            "changed_ranking_count": 0,
            "regressed_case_ids": [],
        }
        gates = {
            "off_identical": True,
            "no_critical_regression": True,
            "no_case_regression": True,
            "no_new_forbidden": True,
            "abstention_not_regressed": True,
            "registry_unambiguous": True,
            "registry_current": True,
            "channels_visible": True,
            "bounded": True,
            "deterministic": True,
        }
        backend = {
            "suites": {
                "v27": copy.deepcopy(suite),
                "challenges_v26": copy.deepcopy(suite),
                "cohort": copy.deepcopy(suite),
            },
            "gates": gates,
        }
        document: dict[str, Any] = {
            "schema": PROMOTION_EVIDENCE_SCHEMA,
            "status": "promotable",
            "registry": {"path": REGISTRY_PATH, "digest": registry_digest},
            "implementation_digest": influence_implementation_digest(),
            "fixture_digests": {
                "v27": "1" * 64,
                "v26": "2" * 64,
                "cohort": "3" * 64,
            },
            "limit": 5,
            "backends": {"local": backend, "cache": copy.deepcopy(backend)},
            "activation_authorized": False,
            "authority": "evidence_only",
            "authorizes_actions": False,
            "evidence_digest": "0" * 64,
        }
        body = copy.deepcopy(document)
        body.pop("evidence_digest")
        document["evidence_digest"] = hashlib.sha256(canonical_json(body)).hexdigest()
        return document

    def write_evidence(self, document: dict[str, Any]) -> str:
        path = self.root / EVIDENCE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical_json(document)
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def configure_enabled(
        self,
        *,
        concepts: list[dict[str, Any]] | None = None,
        registry_digest: str | None = None,
        evidence_path: str = EVIDENCE_PATH,
        evidence_digest: str | None = None,
        write_evidence: bool = True,
    ) -> tuple[str, str]:
        actual_registry_digest = self.write_registry(self.registry_document(concepts))
        configured_registry_digest = registry_digest or actual_registry_digest
        actual_evidence_digest = evidence_digest or "0" * 64
        if write_evidence:
            actual_evidence_digest = self.write_evidence(
                self.promotion_document(actual_registry_digest)
            )
        self.write_config(
            {
                "mode": "enabled",
                "registry": REGISTRY_PATH,
                "registry_digest": configured_registry_digest,
                "promotion_evidence": evidence_path,
                "promotion_evidence_digest": actual_evidence_digest,
            }
        )
        return actual_registry_digest, actual_evidence_digest

    def active(self) -> ActiveInfluence:
        self.configure_enabled()
        active = activate_influence(read_influence_setting(self.root), root=self.root)
        self.assertIsInstance(active, ActiveInfluence)
        return active  # type: ignore[return-value]

    @staticmethod
    def write_golden_corpus(root: Path) -> None:
        files = {
            "alpha.py": "from beta import BetaClient\n\nclass AlphaService:\n    def build_alpha(self):\n        return BetaClient()\n",
            "beta.py": "from gamma import gamma_helper\n\nclass BetaClient:\n    def run(self):\n        return gamma_helper()\n",
            "gamma.py": "def gamma_helper():\n    return 'ready'\n\nclass GammaHelper:\n    pass\n",
            "README.md": "# Alpha deployment guide\n\nUse AlphaService with the beta client.\n",
            "docs/configuration.md": "# Configuration reference\n\nThe service client helper graph is documented here.\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def golden_outputs(
        self, snapshot: Any, setting: InfluenceSetting
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        retrieval_outputs: list[dict[str, Any]] = []
        context_outputs: list[dict[str, Any]] = []
        with mock.patch(
            "palimnex.retrieval.read_influence_setting", return_value=setting
        ):
            for query in GOLDEN_QUERIES:
                for include_graph in (False, True):
                    for limit in (2, 5):
                        for byte_budget in (256, 2048):
                            sources = retrieve_sources(
                                query,
                                root=STABLE_GOLDEN_ROOT,
                                limit=limit,
                                byte_budget=byte_budget,
                                include_graph=include_graph,
                                snapshot=snapshot,
                            )
                            retrieval_outputs.append(sources)
                            with mock.patch(
                                "palimnex.experience.retrieve_sources",
                                return_value=sources,
                            ):
                                context_outputs.append(
                                    assemble_context(
                                        query,
                                        root=STABLE_GOLDEN_ROOT,
                                        limit=limit,
                                        byte_budget=byte_budget,
                                        include_graph=include_graph,
                                    )
                                )
        return retrieval_outputs, context_outputs

    def test_missing_off_and_shadow_match_pre_edit_golden_outputs(self) -> None:
        golden_root = self.root / "golden"
        self.write_golden_corpus(golden_root)
        snapshot = cache_v3.source_snapshot(golden_root)
        for mode in ("off", "shadow"):
            with self.subTest(mode=mode):
                retrieval, contexts = self.golden_outputs(
                    snapshot, InfluenceSetting(mode, None, None, None, None)
                )
                self.assertEqual(len(retrieval), 96)
                # checkout_id hashes root.resolve(); macOS resolves /tmp to /private/tmp.
                resolved = hashlib.sha256(str(STABLE_GOLDEN_ROOT.resolve()).encode()).hexdigest()
                portable = hashlib.sha256(str(STABLE_GOLDEN_ROOT).encode()).hexdigest()
                self.assertTrue(all(item["checkout_id"] == resolved for item in retrieval + contexts))
                self.assertEqual(
                    hashlib.sha256(canonical_json(
                        [{**item, "checkout_id": portable} for item in retrieval]
                    )).hexdigest(),
                    RETRIEVAL_GOLDEN_SHA256,
                )
                self.assertEqual(
                    hashlib.sha256(canonical_json(
                        [{**item, "checkout_id": portable} for item in contexts]
                    )).hexdigest(),
                    CONTEXT_GOLDEN_SHA256,
                )
                self.assertTrue(
                    all("ontology_influence" not in item for item in retrieval)
                )
                self.assertTrue(
                    all(item["schema"] == "project-memory:context:v1" for item in contexts)
                )

    def test_config_modes_equal_explicit_off_for_the_same_checkout(self) -> None:
        for mode in (None, {"mode": "off"}, {"mode": "shadow"}):
            with self.subTest(mode=mode):
                self.write_config(mode)
                expected = retrieve_sources("quasar", root=self.root, influence="off")
                actual = retrieve_sources("quasar", root=self.root)
                self.assertEqual(actual, expected)
                self.assertNotIn("ontology_influence", actual)
                self.assertEqual(
                    assemble_context("quasar", root=self.root)["schema"],
                    "project-memory:context:v1",
                )

    def test_enabled_fuses_ontology_discloses_and_returns_context_v2(self) -> None:
        active = self.active()
        baseline = retrieve_sources("quasar", root=self.root, influence="off")
        influenced = retrieve_sources(
            "quasar", root=self.root, limit=2, byte_budget=2048, influence=active
        )
        self.assertNotEqual(
            [item["pointer"] for item in influenced["results"]],
            [item["pointer"] for item in baseline["results"][:2]],
        )
        self.assertEqual(influenced["results"][0]["path"], "docs/a-target.md")
        self.assertIn("ontology", influenced["results"][0]["channels"])
        disclosure = influenced["ontology_influence"]
        self.assertEqual(disclosure["mode"], "enabled")
        self.assertEqual(disclosure["channel"], "ontology")
        self.assertIs(disclosure["retrieval_influence"], True)
        self.assertEqual(disclosure["contributing_concept_ids"], ["concept.quasar"])
        self.assertEqual(len(influenced["results"]), 2)
        self.assertLessEqual(influenced["candidate_count"], 512)
        self.assertLessEqual(influenced["items_bytes"], influenced["byte_budget"])

        context = assemble_context(
            "quasar", root=self.root, limit=2, byte_budget=2048
        )
        self.assertEqual(context["schema"], "project-memory:context:v2")
        self.assertEqual(context["ontology_influence"], disclosure)
        expected_v1_keys = {
            "schema", "query", "items", "items_bytes", "byte_budget", "budget_unit",
            "ledger_status", "cache_consulted", "retrieval_mode", "scan_scope",
            "corpus_fingerprint", "checkout_id", "candidate_scan_truncated",
            "abstained", "omitted_count", "authority", "authorizes_actions",
        }
        self.assertEqual(set(context) - {"ontology_influence"}, expected_v1_keys)

    def test_activation_refusals_propagate_without_fallback(self) -> None:
        def assert_propagates(reason: str) -> None:
            for operation in (
                lambda: retrieve_sources("quasar", root=self.root),
                lambda: assemble_context("quasar", root=self.root),
            ):
                with self.assertRaises(OntologyInfluenceError) as raised:
                    operation()
                self.assertEqual(raised.exception.reason, reason)

        self.configure_enabled(
            registry_digest="f" * 64,
            evidence_path="missing.json",
            evidence_digest="0" * 64,
            write_evidence=False,
        )
        assert_propagates("registry_digest_mismatch")

        self.configure_enabled(
            evidence_path="missing.json",
            evidence_digest="0" * 64,
            write_evidence=False,
        )
        (self.root / "docs/a-target.md").write_text("changed binding\n", encoding="utf-8")
        assert_propagates("registry_stale")
        (self.root / "docs/a-target.md").write_text(
            "Unrelated target material.\n", encoding="utf-8"
        )

        ambiguous = [
            self.concept("concept.alpha", alias="shared alias"),
            self.concept("concept.beta", alias="shared alias"),
        ]
        self.configure_enabled(
            concepts=ambiguous,
            evidence_path="missing.json",
            evidence_digest="0" * 64,
            write_evidence=False,
        )
        assert_propagates("registry_ambiguous")

        self.configure_enabled(
            evidence_path="missing.json",
            evidence_digest="0" * 64,
            write_evidence=False,
        )
        assert_propagates("evidence_missing")

    def test_shadow_baseline_ignores_enabled_checkout_setting(self) -> None:
        self.configure_enabled()
        expected = retrieve_sources("quasar", root=self.root, influence="off")
        result = shadow_retrieve("quasar", registry=None, root=self.root)
        self.assertEqual(result["baseline"], expected)
        self.assertNotIn("ontology_influence", result["baseline"])

    def test_cache_backend_enabled_discloses_and_off_is_identical(self) -> None:
        active = self.active()
        client = FakeRedis()
        cache_v3.build_index(client, self.root)
        first = retrieve_sources(
            "quasar", root=self.root, client=client, influence="off"
        )
        second = retrieve_sources(
            "quasar", root=self.root, client=client, influence="off"
        )
        self.assertEqual(first, second)
        self.assertTrue(first["cache_consulted"])
        self.assertNotIn("ontology_influence", first)

        influenced = retrieve_sources(
            "quasar", root=self.root, client=client, influence=active
        )
        self.assertTrue(influenced["cache_consulted"])
        self.assertEqual(influenced["ontology_influence"]["mode"], "enabled")
        ontology_items = [
            item for item in influenced["results"] if "ontology" in item["channels"]
        ]
        self.assertTrue(ontology_items)


if __name__ == "__main__":
    unittest.main()
