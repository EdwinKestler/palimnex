from __future__ import annotations

import copy
import json
import re
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

from palimnex.security import scan_bytes


ROOT = Path(__file__).resolve().parents[2]
COHORT_PATH = ROOT / "palimnex/evaluation/semantic-shadow.v1.json"
ONTOLOGY_COHORT_PATH = ROOT / "palimnex/evaluation/ontology-shadow.v1.json"
SCHEMA_PATH = ROOT / "palimnex/schemas/semantic-shadow-cohort.v1.schema.json"
PLACEHOLDER = "{canary}"
CATEGORY_MINIMUMS = {
    "paraphrase": 8,
    "synonym": 6,
    "ambiguity": 3,
    "negative": 5,
    "control": 4,
}
CANARY_RULES = {"aws-access-key", "github-token", "openai-token"}
RUNTIME_PATH = re.compile(r"palimnex/[^/]+\.py")
SOURCE_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def identifier_shaped(token: str) -> bool:
    return "_" in token or any(character.isupper() for character in token[1:])


def lowercase_trigrams(tokens: list[str]) -> set[tuple[str, str, str]]:
    return {
        (first, second, third)
        for first, second, third in zip(tokens, tokens[1:], tokens[2:])
        if all(word.isalpha() and word.islower() for word in (first, second, third))
    }


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


class SemanticShadowCohortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import jsonschema
        from referencing import Registry, Resource

        cls.jsonschema = jsonschema
        cls.cohort = load_object(COHORT_PATH)
        cls.schema = load_object(SCHEMA_PATH)
        registry = Registry().with_resource(
            cls.schema["$id"],
            Resource.from_contents(cls.schema),
        )
        cls.validator = jsonschema.Draft202012Validator(
            cls.schema,
            registry=registry,
        )

    def test_schema_is_valid_and_cohort_validates_locally(self) -> None:
        self.jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.cohort)
        self.assertEqual(self.cohort["schema"], "palimnex:semantic-shadow-cohort:v1")
        self.assertEqual(self.cohort["status"], "frozen")

    def test_repository_categories_ids_and_critical_controls(self) -> None:
        cases = self.cohort["cases"]
        categories = Counter(case["category"] for case in cases)
        self.assertEqual(set(categories), set(CATEGORY_MINIMUMS))
        for category, minimum in CATEGORY_MINIMUMS.items():
            self.assertGreaterEqual(categories[category], minimum)
        critical = [case for case in cases if case["critical"]]
        self.assertGreaterEqual(len(critical), 2)
        self.assertTrue(all(case["category"] == "control" for case in critical))
        all_ids = [case["id"] for case in cases + self.cohort["project_cases"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(case["limit"], 5)
                self.assertTrue(case["note"].endswith("."))
                if case["category"] == "negative":
                    self.assertEqual(case["expected_paths"], [])
                if case["category"] == "ambiguity":
                    self.assertGreaterEqual(len(case["expected_paths"]), 2)

    def test_repository_paths_are_current_runtime_modules(self) -> None:
        expected_modules: set[str] = set()
        for case in self.cohort["cases"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(
                    set(case["expected_paths"]).isdisjoint(case["forbidden_paths"])
                )
                for field in ("expected_paths", "forbidden_paths"):
                    for value in case[field]:
                        self.assertIsNotNone(RUNTIME_PATH.fullmatch(value))
                        path = ROOT / value
                        self.assertTrue(path.is_file())
                        self.assertFalse(path.is_symlink())
                expected_modules.update(case["expected_paths"])
        self.assertGreaterEqual(len(expected_modules), 8)

    def test_queries_are_bounded_unique_and_new(self) -> None:
        queries = [case["query"] for case in self.cohort["cases"]]
        self.assertEqual(len(queries), len(set(queries)))
        ontology_queries = {
            case["query"] for case in load_object(ONTOLOGY_COHORT_PATH)["cases"]
        }
        for case in self.cohort["cases"]:
            with self.subTest(case=case["id"]):
                query = case["query"]
                self.assertEqual(query, query.strip())
                self.assertLessEqual(len(query), 200)
                self.assertNotIn(query, ontology_queries)

    def test_paraphrase_and_synonym_queries_are_source_isolated(self) -> None:
        for case in self.cohort["cases"]:
            if case["category"] not in {"paraphrase", "synonym"}:
                continue
            query_tokens = SOURCE_TOKEN_RE.findall(case["query"])
            query_identifiers = {
                token for token in query_tokens if identifier_shaped(token)
            }
            query_trigrams = lowercase_trigrams(query_tokens)
            for relative in case["expected_paths"]:
                with self.subTest(case=case["id"], expected_path=relative):
                    source_tokens = SOURCE_TOKEN_RE.findall(
                        (ROOT / relative).read_text(encoding="utf-8")
                    )
                    shared_identifiers = query_identifiers.intersection(source_tokens)
                    self.assertEqual(shared_identifiers, set())
                    shared_trigrams = query_trigrams.intersection(
                        lowercase_trigrams(source_tokens)
                    )
                    self.assertEqual(shared_trigrams, set())

    def test_raw_cohort_passes_privacy_admission(self) -> None:
        self.assertEqual(scan_bytes(COHORT_PATH.read_bytes()), [])

    def test_projects_are_small_normalized_and_referenced(self) -> None:
        projects = self.cohort["projects"]
        referenced = {case["project"] for case in self.cohort["project_cases"]}
        self.assertEqual(referenced, set(projects))
        for project_id, project in projects.items():
            with self.subTest(project=project_id):
                documents = project["documents"]
                self.assertGreaterEqual(len(documents), 2)
                self.assertLessEqual(len(documents), 6)
                for path, text in {**documents, **project["after"]}.items():
                    self.assertFalse(Path(path).is_absolute())
                    self.assertNotIn("..", Path(path).parts)
                    if text is not None:
                        self.assertLess(len(text.encode("utf-8")), 4096)

    def test_drift_cases_move_the_relevant_source(self) -> None:
        drift_cases = [
            case for case in self.cohort["project_cases"]
            if case["category"] == "drift"
        ]
        self.assertGreaterEqual(len(drift_cases), 2)
        for case in drift_cases:
            with self.subTest(case=case["id"]):
                project = self.cohort["projects"][case["project"]]
                before = dict(project["documents"])
                after = dict(before)
                for path, value in project["after"].items():
                    if value is None:
                        after.pop(path, None)
                    else:
                        after[path] = value
                self.assertNotEqual(before, after)
                for path in case["expected_paths"]:
                    self.assertNotIn(path, before)
                    self.assertIn(path, after)
                    self.assertIsNotNone(project["after"].get(path))
                for path in case["forbidden_paths"]:
                    self.assertIn(path, before)
                    self.assertNotIn(path, after)
                    self.assertIsNone(project["after"].get(path))

    def test_privacy_cases_place_exactly_one_runtime_canary(self) -> None:
        privacy_cases = [
            case for case in self.cohort["project_cases"]
            if case["category"] == "privacy_canary"
        ]
        self.assertGreaterEqual(len(privacy_cases), 3)
        query_rules = {
            case["canary_rule"] for case in privacy_cases
            if case["canary_kind"] == "query"
        }
        self.assertGreaterEqual(len(query_rules), 2)
        self.assertTrue(any(case["canary_kind"] == "corpus" for case in privacy_cases))
        for case in privacy_cases:
            with self.subTest(case=case["id"]):
                self.assertIn(case["canary_rule"], CANARY_RULES)
                documents = self.cohort["projects"][case["project"]]["documents"]
                document_hits = {
                    path: text.count(PLACEHOLDER)
                    for path, text in documents.items()
                    if PLACEHOLDER in text
                }
                total = case["query"].count(PLACEHOLDER) + sum(document_hits.values())
                self.assertEqual(total, 1)
                if case["canary_kind"] == "query":
                    self.assertEqual(case["query"].count(PLACEHOLDER), 1)
                    self.assertEqual(document_hits, {})
                    self.assertEqual(case["expected_paths"], [])
                    self.assertEqual(case["forbidden_paths"], [])
                else:
                    self.assertEqual(case["query"].count(PLACEHOLDER), 0)
                    self.assertEqual(sum(document_hits.values()), 1)
                    self.assertEqual(case["expected_paths"], [])
                    self.assertEqual(case["forbidden_paths"], list(document_hits))

    def test_schema_rejects_unexpected_and_misclassified_fields(self) -> None:
        unexpected = copy.deepcopy(self.cohort)
        unexpected["cases"][0]["retrieval_result"] = []
        self.assertTrue(list(self.validator.iter_errors(unexpected)))

        critical = copy.deepcopy(self.cohort)
        critical["cases"][0]["critical"] = True
        self.assertTrue(list(self.validator.iter_errors(critical)))

        invalid_rule = copy.deepcopy(self.cohort)
        privacy = next(
            case for case in invalid_rule["project_cases"]
            if case["category"] == "privacy_canary"
        )
        privacy["canary_rule"] = "unknown-rule"
        self.assertTrue(list(self.validator.iter_errors(invalid_rule)))

    def test_cohort_is_sorted_pretty_json_with_trailing_newline(self) -> None:
        expected = json.dumps(
            self.cohort,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        self.assertEqual(COHORT_PATH.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
