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
from palimnex.concepts import (
    ConceptRegistry,
    ConceptRegistryError,
    canonical_registry_digest,
    parse_registry,
)
from palimnex.durable import canonical_json
from palimnex.locators import SourceRange, select_range
from palimnex.ontology_shadow import ShadowComparisonError
from palimnex.retrieval import retrieve_sources, shadow_retrieve


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "palimnex/tests/fixtures/ontology/cases.v0.json"
MATRIX_SHA256 = "a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b"
PROJECT = {
    "project_slug": "fixture",
    "project_id": "11111111-1111-4111-8111-111111111111",
}
STABLE_GOLDEN_ROOT = Path("/tmp/palimnex-retrieval-golden-corpus-v1")
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
GOLDEN_DIGESTS = {
    ("AlphaService", 256): "01333b80304c04484cb2659a44e81ff15bccc3383f0409c99d328884198b2ff5",
    ("AlphaService", 2048): "b503d0222fe1f8b0ec5ec235f8a98a495d3796fa2a43fe2383b67643e4276ca0",
    ("BetaClient", 256): "b2a23db18db96174baaa8641f725dff33b3a4cbe42e552b3d0a0255dbd0517b5",
    ("BetaClient", 2048): "7aa1c5df57d8d25c9c42a7b6de4c33eac451ed0d6ef5a6c25560e9fd25f2f7a1",
    ("GammaHelper", 256): "aa8fcf184ad2b26f1fb76dd354fe46ea60e8a5da4641a28a3a3762fc9c5aea52",
    ("GammaHelper", 2048): "41b9620079cf4bdd13ced71b74552204be483eb699e3da59185342a35173aeef",
    ("alpha service", 256): "0c6f44bb9ed42e80ba7c454298293d9d5f8896d006a56c1be3561b1646a82d08",
    ("alpha service", 2048): "afc0e1fa4b750a13a92f7bd1cd8ad9fecccba392d8bfb714e959dea2b4d5e444",
    ("beta client", 256): "117e2c721bddf2409c42a84d0a18a185845ea938f39bc994b2a9ba8e653cb8a7",
    ("beta client", 2048): "a4dd2288574a2390dd8e84640cb92244b945cda035d54b9c1a9ffbe176d3da51",
    ("build alpha", 256): "5577c85cac65263ba46a898d5ab2b81d30449ffacdebbb15551649723bc9cdaf",
    ("build alpha", 2048): "c99e3ba4211de7323db41f016d51ce483514b0f35800db718c22202a2722726a",
    ("configuration reference", 256): "506cae70b6a9a67e44b6932460d95f9cf0f15d0aeab13b4cbb6388e9d85a3659",
    ("configuration reference", 2048): "17f8e8795c4f4d86217a558a93a0f9f4abd7b4c2699479714ad4ec590b98a6e1",
    ("deployment guide", 256): "ab76acf208adb624f045ab8ca780dc3beedc488de6b826192657de56a2ca5c28",
    ("deployment guide", 2048): "417bd6978835b1cba6ac8a9bf16caf1d356b5d8bd2c33f8f85a988b008bfb63c",
    ("gamma helper", 256): "06c65ddc2903627f0b71dd8047628056e99446e51fefa007935c1b62524d609c",
    ("gamma helper", 2048): "34bc27a4186f41df95e6ad039f86b791e62b2d910ed724259d06912b92640726",
    ("graph imports", 256): "82856b473d872b692245cd5a53f19045b350dbb7efcaf65bd0805125dce41221",
    ("graph imports", 2048): "865c3e4ee2091acd43d35eb62f9d51ed93bec6a2f4b625cf9dff6a2d0b9832fa",
    ("missing phrase", 256): "7dec6babf90cdfa597f7de59e819fa3c0f709aa71f4a94e0ddefe423ba957260",
    ("missing phrase", 2048): "bdf1b1ce25c576cf3e5a1f590bdc0b8af0370e1ee85cf74e3d7932d6575ad617",
    ("service client helper", 256): "5fa7500e5d6e9b17aadc33835ec498e17b4f24cf88d47345c30961a3fe9af545",
    ("service client helper", 2048): "91a99d6d6efd8f79be423cf885a38e2824d92da715f0cbc836104dc049c4a8ed",
}


class RetrievalShadowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".palimnex.json").write_text(
            json.dumps(PROJECT),
            encoding="utf-8",
        )

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def binding(
        self,
        relative: str,
        *,
        start: int = 1,
        end: int = 1,
        digest: str | None = None,
    ) -> dict[str, Any]:
        raw = (self.root / relative).read_bytes()
        selected = select_range(raw, SourceRange("lines", start, end))
        return {
            "scheme": "repo",
            "source_id": relative,
            "version": hashlib.sha256(raw).hexdigest(),
            "range": {"unit": "lines", "start": start, "end": end},
            "digest": digest or hashlib.sha256(selected).hexdigest(),
        }

    def concept(
        self,
        concept_id: str,
        alias: str,
        bindings: list[dict[str, Any]],
        *,
        status: str = "approved",
    ) -> dict[str, Any]:
        return {
            "concept_id": concept_id,
            "canonical_name": concept_id.replace(".", " "),
            "aliases": [alias],
            "definition": "Retrieval shadow test concept.",
            "source_bindings": bindings,
            "status": status,
            "provenance": {"origin": "manual"},
        }

    def registry(
        self,
        concepts: list[dict[str, Any]],
        *,
        kind: str = "approved_registry",
    ) -> ConceptRegistry:
        document: dict[str, Any] = {
            "schema": "palimnex:concept-registry:v1",
            "project": PROJECT,
            "registry_version": 1,
            "registry_kind": kind,
            "concepts": concepts,
            "registry_digest": "0" * 64,
            "authority": "historical_only",
            "authorizes_actions": False,
        }
        document["registry_digest"] = canonical_registry_digest(document)
        return parse_registry(document, root=self.root)

    def write_golden_corpus(self) -> Path:
        golden_root = self.root / "golden"
        files = {
            "alpha.py": "from beta import BetaClient\n\nclass AlphaService:\n    def build_alpha(self):\n        return BetaClient()\n",
            "beta.py": "from gamma import gamma_helper\n\nclass BetaClient:\n    def run(self):\n        return gamma_helper()\n",
            "gamma.py": "def gamma_helper():\n    return 'ready'\n\nclass GammaHelper:\n    pass\n",
            "README.md": "# Alpha deployment guide\n\nUse AlphaService with the beta client.\n",
            "docs/configuration.md": "# Configuration reference\n\nThe service client helper graph is documented here.\n",
        }
        for relative, content in files.items():
            path = golden_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return golden_root

    def test_temporary_corpus_golden_digests_and_baseline_identity(self) -> None:
        golden_root = self.write_golden_corpus()
        snapshot = cache_v3.source_snapshot(golden_root)
        checked = 0
        for query in GOLDEN_QUERIES:
            for include_graph in (False, True):
                for limit in (2, 5):
                    for byte_budget in (256, 2048):
                        with self.subTest(
                            query=query,
                            include_graph=include_graph,
                            limit=limit,
                            byte_budget=byte_budget,
                        ):
                            baseline = retrieve_sources(
                                query,
                                root=STABLE_GOLDEN_ROOT,
                                limit=limit,
                                byte_budget=byte_budget,
                                include_graph=include_graph,
                                snapshot=snapshot,
                            )
                            digest = hashlib.sha256(canonical_json(baseline)).hexdigest()
                            self.assertEqual(digest, GOLDEN_DIGESTS[(query, byte_budget)])
                            shadow = shadow_retrieve(
                                query,
                                registry=None,
                                root=STABLE_GOLDEN_ROOT,
                                limit=limit,
                                byte_budget=byte_budget,
                                include_graph=include_graph,
                                snapshot=snapshot,
                            )
                            self.assertEqual(shadow["baseline"], baseline)
                            self.assertTrue(shadow["comparison"]["diff"]["identical"])
                            checked += 1
        self.assertEqual(checked, 96)

    def test_repository_queries_have_same_run_baseline_identity(self) -> None:
        snapshot = cache_v3.source_snapshot(ROOT)
        queries = (
            "retrieve sources",
            "rank fusion",
            "concept registry",
            "coverage receipt",
            "privacy scanner",
            "source resolver",
        )
        for query in queries:
            with self.subTest(query=query):
                baseline = retrieve_sources(query, root=ROOT, snapshot=snapshot)
                shadow = shadow_retrieve(
                    query,
                    registry=None,
                    root=ROOT,
                    snapshot=snapshot,
                )
                self.assertEqual(shadow["baseline"], baseline)
                self.assertTrue(shadow["comparison"]["diff"]["identical"])

    def test_ontology_promotes_bound_chunk_without_changing_baseline(self) -> None:
        self.write("docs/a-target.md", "Unrelated target material.\n")
        self.write("docs/z-popular.md", "Quasar quasar quasar lexical winner.\n")
        registry = self.registry(
            [self.concept("concept.quasar", "quasar", [self.binding("docs/a-target.md")])]
        )
        snapshot = cache_v3.source_snapshot(self.root)
        baseline = retrieve_sources(
            "quasar",
            root=self.root,
            include_graph=False,
            snapshot=snapshot,
        )
        result = shadow_retrieve(
            "quasar",
            registry=registry,
            root=self.root,
            include_graph=False,
            snapshot=snapshot,
        )
        self.assertEqual(result["baseline"], baseline)
        self.assertEqual(baseline["results"][0]["path"], "docs/z-popular.md")
        self.assertEqual(
            result["comparison"]["shadow"]["items"][0]["pointer"],
            "docs/a-target.md:1-1",
        )
        self.assertFalse(result["comparison"]["diff"]["identical"])
        self.assertFalse(result["comparison"]["returned_ranking_changed"])

    def test_ambiguous_stale_and_uncovered_concepts_do_not_change_shadow(self) -> None:
        self.write("docs/a.md", "Shared lexical result.\n")
        self.write("docs/b.md", "Second source.\n")
        external = {
            "scheme": "fixture",
            "source_id": "record-1",
            "version": "v1",
            "range": {"unit": "bytes", "start": 0, "end": 1},
            "digest": hashlib.sha256(b"x").hexdigest(),
        }
        registry = self.registry(
            [
                self.concept("concept.first", "shared", [self.binding("docs/a.md")]),
                self.concept("concept.second", "shared", [self.binding("docs/b.md")]),
                self.concept("concept.stale", "drifted", [self.binding("docs/a.md", digest="f" * 64)]),
                self.concept("concept.uncovered", "detached", [external]),
            ]
        )
        result = shadow_retrieve(
            "shared drifted detached",
            registry=registry,
            root=self.root,
        )
        comparison = result["comparison"]
        self.assertTrue(comparison["diff"]["identical"])
        self.assertEqual(
            comparison["ontology_channel"]["excluded_ambiguous"],
            ["concept.first", "concept.second"],
        )
        self.assertEqual(comparison["ontology_channel"]["excluded_stale"], ["concept.stale"])
        self.assertEqual(
            comparison["ontology_channel"]["excluded_uncovered"],
            ["concept.uncovered"],
        )

    def test_candidate_registry_is_refused_without_shadow_result(self) -> None:
        candidate = self.registry(
            [self.concept("concept.candidate", "candidate", [], status="candidate")],
            kind="candidate_set",
        )
        self.write("docs/source.md", "Candidate baseline.\n")
        with mock.patch("palimnex.retrieval.build_shadow_comparison") as builder:
            with self.assertRaises(ShadowComparisonError) as raised:
                shadow_retrieve("candidate", registry=candidate, root=self.root)
        self.assertEqual(raised.exception.reason, "registry_kind_mismatch")
        builder.assert_not_called()

    def test_all_four_channel_ranks_are_visible(self) -> None:
        self.write(
            "docs/decision.md",
            "# Decision\n\nDecision details link to [Target](target.md).\n",
        )
        self.write("docs/target.md", "# Target\n\nBound support.\n")
        registry = self.registry(
            [self.concept("concept.decision", "decision", [self.binding("docs/target.md")])]
        )
        result = shadow_retrieve("decision", registry=registry, root=self.root)
        visible = {
            name
            for item in result["comparison"]["shadow"]["items"]
            for name in item["channels"]
        }
        self.assertEqual(visible, {"lexical", "symbol", "graph", "ontology"})

    def test_fusion_cap_limit_and_byte_budget_are_preserved(self) -> None:
        for index in range(513):
            self.write(f"docs/source-{index:03d}.md", "alpha\n")
        snapshot = cache_v3.source_snapshot(self.root)
        result = shadow_retrieve(
            "alpha",
            registry=None,
            root=self.root,
            limit=3,
            byte_budget=2048,
            snapshot=snapshot,
        )
        baseline = result["baseline"]
        comparison = result["comparison"]
        self.assertEqual(baseline["candidate_count"], 512)
        self.assertLessEqual(len(baseline["results"]), 3)
        self.assertLessEqual(baseline["items_bytes"], 2048)
        self.assertEqual(comparison["shadow"]["candidate_count"], 512)
        self.assertLessEqual(len(comparison["shadow"]["items"]), 3)
        self.assertLessEqual(comparison["shadow"]["items_bytes"], 2048)

    def test_frozen_secret_source_is_refused_without_echo_or_comparison(self) -> None:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(MATRIX_PATH.read_bytes()).hexdigest(), MATRIX_SHA256)
        case = next(item for item in matrix["cases"] if item["case_id"] == "ONT-SEC-002")
        self.assertEqual(case["gates_phase"], 3)
        self.assertTrue(case["binding_digests_are_placeholders"])
        document = copy.deepcopy(case["registry_fixture"])
        (self.root / ".palimnex.json").write_text(json.dumps(document["project"]), encoding="utf-8")
        self.write("docs/safe.md", "Safe baseline source.\n")
        snapshot = cache_v3.source_snapshot(self.root)
        recipe = case["canary_recipe"]
        self.assertEqual(recipe["operation"], "join")
        canary = "".join(tuple(recipe["fragments"]))
        binding = document["concepts"][0]["source_bindings"][0]
        raw = canary.encode("utf-8") + b"xxxx"
        target = self.root / binding["source_id"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        bounds = SourceRange(**binding["range"])
        self.assertEqual(bounds.unit, "bytes")
        selected = raw[bounds.start:bounds.end]
        binding["version"] = hashlib.sha256(raw).hexdigest()
        binding["digest"] = hashlib.sha256(selected).hexdigest()
        document["registry_digest"] = canonical_registry_digest(document)
        registry = parse_registry(document, root=self.root)
        with mock.patch("palimnex.retrieval.build_shadow_comparison") as builder:
            with self.assertRaises(ConceptRegistryError) as raised:
                shadow_retrieve(
                    case["query"],
                    registry=registry,
                    root=self.root,
                    snapshot=snapshot,
                )
        self.assertEqual(raised.exception.reason, "source_privacy_refused")
        self.assertNotIn(canary, str(raised.exception))
        builder.assert_not_called()

    def test_frozen_candidate_collision_does_not_make_approved_ambiguous(self) -> None:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(MATRIX_PATH.read_bytes()).hexdigest(), MATRIX_SHA256)
        case = next(item for item in matrix["cases"] if item["case_id"] == "ONT-CAND-002")
        self.assertEqual(case["gates_phase"], 3)
        self.assertTrue(case["binding_digests_are_placeholders"])
        approved_document = copy.deepcopy(case["registry_fixture"])
        binding = approved_document["concepts"][0]["source_bindings"][0]
        raw = (ROOT / binding["source_id"]).read_bytes()
        selected = select_range(raw, SourceRange(**binding["range"]))
        binding["version"] = hashlib.sha256(raw).hexdigest()
        binding["digest"] = hashlib.sha256(selected).hexdigest()
        approved_document["registry_digest"] = canonical_registry_digest(approved_document)
        approved = parse_registry(approved_document, root=ROOT)

        candidate_document = copy.deepcopy(case["candidate_registry_fixture"])
        candidate_document["registry_digest"] = canonical_registry_digest(candidate_document)
        candidate = parse_registry(candidate_document, root=ROOT)
        self.assertEqual(candidate.registry_kind, "candidate_set")

        snapshot = cache_v3.source_snapshot(ROOT)
        baseline = retrieve_sources(case["query"], root=ROOT, snapshot=snapshot)
        result = shadow_retrieve(
            case["query"],
            registry=approved,
            root=ROOT,
            snapshot=snapshot,
        )
        self.assertEqual(result["baseline"], baseline)
        channel = result["comparison"]["ontology_channel"]
        self.assertEqual(channel["recognized_concept_ids"], ["concept.approved_source"])
        self.assertEqual(channel["ambiguous_concept_ids"], [])
        self.assertEqual(channel["contributing_concept_ids"], ["concept.approved_source"])
        with self.assertRaises(ShadowComparisonError):
            shadow_retrieve(
                case["query"],
                registry=candidate,
                root=ROOT,
                snapshot=snapshot,
            )


if __name__ == "__main__":
    unittest.main()
