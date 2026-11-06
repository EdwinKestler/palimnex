from __future__ import annotations

import copy
import json
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from palimnex.concepts import (
    canonical_registry_digest,
    match_aliases,
    normalize_alias,
    parse_registry,
)
from palimnex.security import scan_bytes


ROOT = Path(__file__).resolve().parents[2]
COHORT_PATH = ROOT / "palimnex/evaluation/ontology-shadow.v1.json"
ZERO_DIGEST = "0" * 64
CASE_FIELDS = {
    "id",
    "category",
    "query",
    "limit",
    "expected_paths",
    "forbidden_paths",
    "critical",
    "expect_ontology_contribution",
    "note",
}
CATEGORY_MINIMUMS = {
    "alias": 8,
    "paraphrase": 4,
    "ambiguity": 2,
    "negative": 4,
    "control": 4,
}
EXPECTED_BINDING_ANCHORS = {
    "concept.audit_graph": "def build_audit_graph(",
    "concept.concept_registry": "class ConceptRegistry:",
    "concept.coverage_receipt": "def query_digest(",
    "concept.durable_ledger": "class MemoryLedger:",
    "concept.migration_registry": "class Migration:",
    "concept.privacy_scanner": "def scan_text(",
    "concept.reader_leases": "def _reader_lease_key(",
    "concept.repository_graph": "def extract_file_graph(",
    "concept.retention_policy": "def validate_policy(",
    "concept.rrf_fusion": "def _fuse_rankings(",
    "concept.semantic_hold": "def semantic_status(",
    "concept.source_locators": "class SourceLocator:",
}


def load_cohort() -> dict[str, Any]:
    value = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("ontology shadow cohort must be an object")
    return value


class OntologyShadowCohortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cohort = load_cohort()
        registry_document = copy.deepcopy(cls.cohort["registry"])
        registry_document["registry_digest"] = canonical_registry_digest(registry_document)
        cls.registry = parse_registry(
            registry_document,
            root=ROOT,
            expected_kind="approved_registry",
            allow_placeholder_digests=True,
        )

    def test_frozen_structure_categories_and_unique_ids(self) -> None:
        self.assertEqual(
            set(self.cohort),
            {"schema", "status", "binding_digests_are_placeholders", "registry", "cases"},
        )
        self.assertEqual(self.cohort["schema"], "palimnex:ontology-shadow-cohort:v1")
        self.assertEqual(self.cohort["status"], "frozen")
        self.assertIs(self.cohort["binding_digests_are_placeholders"], True)
        cases = self.cohort["cases"]
        self.assertGreaterEqual(len(cases), 24)
        self.assertLessEqual(len(cases), 30)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        categories = Counter(case["category"] for case in cases)
        self.assertEqual(set(categories), set(CATEGORY_MINIMUMS))
        for category, minimum in CATEGORY_MINIMUMS.items():
            self.assertGreaterEqual(categories[category], minimum)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(set(case), CASE_FIELDS)
                self.assertIs(type(case["id"]), str)
                self.assertTrue(case["id"])
                self.assertIs(type(case["query"]), str)
                self.assertTrue(case["query"].strip())
                self.assertEqual(case["limit"], 5)
                self.assertIs(type(case["critical"]), bool)
                self.assertIs(type(case["expect_ontology_contribution"]), bool)
                self.assertIs(type(case["note"]), str)
                self.assertTrue(case["note"].strip())
                for field in ("expected_paths", "forbidden_paths"):
                    self.assertIsInstance(case[field], list)
                    self.assertEqual(len(case[field]), len(set(case[field])))
                    for path in case[field]:
                        self.assertIs(type(path), str)
                        self.assertFalse(Path(path).is_absolute())
                        self.assertNotIn("..", Path(path).parts)
                if case["category"] == "negative":
                    self.assertEqual(case["expected_paths"], [])

    def test_registry_is_evaluation_only_and_parses_with_placeholders(self) -> None:
        registry = self.cohort["registry"]
        self.assertEqual(registry["registry_kind"], "approved_registry")
        self.assertEqual(registry["registry_digest"], ZERO_DIGEST)
        self.assertEqual(registry["project"], {
            "project_slug": "palimnex",
            "project_id": "7d96bcda-e4bc-4aa4-be3e-24f761bacbd8",
        })
        self.assertEqual(registry["authority"], "historical_only")
        self.assertIs(registry["authorizes_actions"], False)
        self.assertGreaterEqual(len(self.registry.concepts), 10)
        self.assertLessEqual(len(self.registry.concepts), 16)
        self.assertTrue(all(concept.status == "approved" for concept in self.registry.concepts))
        for concept in registry["concepts"]:
            with self.subTest(concept=concept["concept_id"]):
                canonical_key = normalize_alias(concept["canonical_name"])
                self.assertNotIn(canonical_key, concept["aliases"])
                for alias in concept["aliases"]:
                    self.assertEqual(alias, normalize_alias(alias))
                for binding in concept["source_bindings"]:
                    self.assertEqual(binding["version"], ZERO_DIGEST)
                    self.assertEqual(binding["digest"], ZERO_DIGEST)

    def test_bound_paths_and_line_ranges_are_current(self) -> None:
        self.assertEqual(
            set(EXPECTED_BINDING_ANCHORS),
            {concept["concept_id"] for concept in self.cohort["registry"]["concepts"]},
        )
        for concept in self.cohort["registry"]["concepts"]:
            for binding in concept["source_bindings"]:
                with self.subTest(concept=concept["concept_id"], path=binding["source_id"]):
                    self.assertEqual(binding["scheme"], "repo")
                    source_path = ROOT / binding["source_id"]
                    self.assertTrue(source_path.is_file())
                    self.assertFalse(source_path.is_symlink())
                    bounds = binding["range"]
                    self.assertEqual(bounds["unit"], "lines")
                    source_lines = source_path.read_text(encoding="utf-8").splitlines()
                    line_count = len(source_lines)
                    self.assertGreaterEqual(bounds["start"], 1)
                    self.assertLessEqual(bounds["start"], bounds["end"])
                    self.assertLessEqual(bounds["end"], line_count)
                    expected_anchor = EXPECTED_BINDING_ANCHORS[concept["concept_id"]]
                    self.assertTrue(
                        source_lines[bounds["start"] - 1].lstrip().startswith(expected_anchor),
                        f"binding must start at {expected_anchor!r}",
                    )

    def test_exactly_one_two_concept_alias_collision(self) -> None:
        owners: dict[str, set[str]] = defaultdict(set)
        for concept in self.registry.active_concepts:
            for key in (normalize_alias(concept.canonical_name), *concept.aliases):
                owners[key].add(concept.concept_id)
        collisions = {key: ids for key, ids in owners.items() if len(ids) > 1}
        self.assertEqual(collisions, {
            "memory graph": {"concept.audit_graph", "concept.repository_graph"}
        })

    def test_case_vocabulary_matches_the_registry(self) -> None:
        for case in self.cohort["cases"]:
            result = match_aliases(self.registry, case["query"])
            with self.subTest(case=case["id"]):
                if case["category"] == "alias":
                    self.assertTrue(result.recognized_concept_ids)
                    self.assertFalse(result.ambiguities)
                    self.assertIs(case["expect_ontology_contribution"], True)
                elif case["category"] == "ambiguity":
                    self.assertTrue(result.ambiguities)
                    self.assertEqual(
                        result.ambiguous_concept_ids,
                        ("concept.audit_graph", "concept.repository_graph"),
                    )
                    self.assertIs(case["expect_ontology_contribution"], False)
                else:
                    self.assertFalse(result.recognized_concept_ids)
                    self.assertFalse(result.ambiguities)
                    self.assertIs(case["expect_ontology_contribution"], False)

    def test_cohort_bytes_pass_privacy_admission(self) -> None:
        self.assertEqual(scan_bytes(COHORT_PATH.read_bytes()), [])


if __name__ == "__main__":
    unittest.main()
