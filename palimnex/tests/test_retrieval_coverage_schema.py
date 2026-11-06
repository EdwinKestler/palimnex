from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from palimnex.durable import canonical_json


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRECTORY = ROOT / "palimnex/schemas"
FIXTURE_DIRECTORY = ROOT / "palimnex/tests/fixtures/retrieval_coverage"
ACCEPTED_EXAMPLE_DIRECTORY = ROOT / "artifacts/design/ontology-phase-0/coverage/examples"
SCHEMA_NAMES = (
    "concept-registry.v1.schema.json",
    "source-locator.v1.schema.json",
    "retrieval-coverage.v1.schema.json",
    "explain-search.v1.schema.json",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def coverage_contract_errors(document: dict[str, Any]) -> list[str]:
    """Check accepted cross-field rules that JSON Schema cannot express."""
    errors: list[str] = []
    coverage = document["coverage"]
    for name in ("numerator", "denominator"):
        if type(coverage[name]) is not int:
            errors.append(f"coverage.{name} must be a JSON integer")

    covered = {item["concept_id"] for item in document["covered_concepts"]["items"]}
    uncovered = set(document["uncovered_concepts"]["items"])
    stale = {item["concept_id"] for item in document["stale_concepts"]["items"]}
    ambiguous = {
        concept_id
        for item in document["ambiguous_concepts"]["items"]
        for concept_id in item["candidate_concept_ids"]
    }
    categories = (covered, uncovered, stale, ambiguous)
    if any(
        categories[left] & categories[right]
        for left in range(len(categories))
        for right in range(left + 1, len(categories))
    ):
        errors.append("coverage classifications must be disjoint")

    body = {key: value for key, value in document.items() if key != "receipt_digest"}
    actual_digest = hashlib.sha256(canonical_json(body)).hexdigest()
    if document["receipt_digest"] != actual_digest:
        errors.append("receipt_digest does not match canonical content")
    return errors


class RetrievalCoverageSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import jsonschema
        from referencing import Registry, Resource

        cls.jsonschema = jsonschema
        cls.schemas = {
            name: load_json(SCHEMA_DIRECTORY / name)
            for name in SCHEMA_NAMES
        }
        cls.registry = Registry().with_resources(
            (
                (schema["$id"], Resource.from_contents(schema))
                for schema in cls.schemas.values()
            )
        )
        cls.coverage_validator = jsonschema.Draft202012Validator(
            cls.schemas["retrieval-coverage.v1.schema.json"],
            registry=cls.registry,
        )
        cls.explain_validator = jsonschema.Draft202012Validator(
            cls.schemas["explain-search.v1.schema.json"],
            registry=cls.registry,
        )

    def errors_for(self, document: dict[str, Any]) -> list[str]:
        if document.get("schema") == "palimnex:retrieval-coverage:v1":
            schema_errors = list(self.coverage_validator.iter_errors(document))
            if schema_errors:
                return [error.message for error in schema_errors]
            return coverage_contract_errors(document)
        if document.get("schema") == "palimnex:explain-search:v1":
            return [error.message for error in self.explain_validator.iter_errors(document)]
        return ["unknown fixture schema"]

    def test_public_schemas_are_valid_and_refs_resolve_locally(self) -> None:
        for name, schema in self.schemas.items():
            with self.subTest(schema=name):
                self.jsonschema.Draft202012Validator.check_schema(schema)
        enabled = load_json(FIXTURE_DIRECTORY / "valid/explain-search-enabled.json")
        self.explain_validator.validate(enabled)

    def test_accepted_coverage_examples_are_byte_identical(self) -> None:
        for category in ("valid", "invalid"):
            accepted_paths = sorted((ACCEPTED_EXAMPLE_DIRECTORY / category).glob("*.json"))
            copied_paths = sorted((FIXTURE_DIRECTORY / category).glob("*.json"))
            copied_by_name = {path.name: path for path in copied_paths}
            for accepted_path in accepted_paths:
                with self.subTest(category=category, path=accepted_path.name):
                    self.assertIn(accepted_path.name, copied_by_name)
                    self.assertEqual(
                        accepted_path.read_bytes(),
                        copied_by_name[accepted_path.name].read_bytes(),
                    )

    def test_valid_fixtures_validate_and_coverage_digests_match(self) -> None:
        paths = sorted((FIXTURE_DIRECTORY / "valid").glob("*.json"))
        self.assertEqual(len(paths), 9)
        for path in paths:
            with self.subTest(path=path.name):
                document = load_json(path)
                self.assertEqual(self.errors_for(document), [])
                coverage = (
                    document
                    if document["schema"] == "palimnex:retrieval-coverage:v1"
                    else document["coverage"]
                )
                if coverage is not None:
                    self.assertEqual(coverage_contract_errors(coverage), [])

    def test_invalid_fixtures_are_rejected(self) -> None:
        paths = sorted((FIXTURE_DIRECTORY / "invalid").glob("*.json"))
        self.assertEqual(len(paths), 10)
        for path in paths:
            with self.subTest(path=path.name):
                document = load_json(path)
                self.assertTrue(self.errors_for(document))

    def test_explain_search_coverage_state_is_exact(self) -> None:
        absent = load_json(FIXTURE_DIRECTORY / "valid/explain-search-registry-absent.json")
        self.assertIsNone(absent["coverage"])
        self.assertEqual(absent["coverage_state"], "registry_absent")
        enabled = load_json(FIXTURE_DIRECTORY / "valid/explain-search-enabled.json")
        self.assertIsInstance(enabled["coverage"], dict)
        self.assertEqual(enabled["coverage_state"], "enabled")


if __name__ == "__main__":
    unittest.main()
