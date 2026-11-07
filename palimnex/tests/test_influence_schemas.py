from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from palimnex.durable import canonical_json


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRECTORY = ROOT / "palimnex/schemas"
FIXTURE_DIRECTORY = ROOT / "palimnex/tests/fixtures/ontology_influence"
SCHEMA_NAMES = (
    "concept-registry.v1.schema.json",
    "source-locator.v1.schema.json",
    "retrieval-coverage.v1.schema.json",
    "context.v2.schema.json",
    "explain-search.v2.schema.json",
    "ontology-promotion-evidence.v1.schema.json",
)
TARGET_SCHEMAS = {
    "project-memory:context:v2": "context.v2.schema.json",
    "palimnex:explain-search:v2": "explain-search.v2.schema.json",
    "palimnex:ontology-promotion-evidence:v1": (
        "ontology-promotion-evidence.v1.schema.json"
    ),
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def evidence_contract_errors(document: dict[str, Any]) -> list[str]:
    body = {key: value for key, value in document.items() if key != "evidence_digest"}
    actual = hashlib.sha256(canonical_json(body)).hexdigest()
    if document.get("evidence_digest") != actual:
        return ["evidence_digest does not match canonical content"]
    return []


class InfluenceSchemaTests(unittest.TestCase):
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
        cls.validators = {
            identifier: jsonschema.Draft202012Validator(
                cls.schemas[name], registry=cls.registry
            )
            for identifier, name in TARGET_SCHEMAS.items()
        }

    def errors_for(self, document: dict[str, Any]) -> list[str]:
        identifier = document.get("schema")
        validator = self.validators.get(identifier)
        if validator is None:
            return ["unknown fixture schema"]
        schema_errors = list(validator.iter_errors(document))
        if schema_errors:
            return [error.message for error in schema_errors]
        if identifier == "palimnex:ontology-promotion-evidence:v1":
            return evidence_contract_errors(document)
        return []

    def test_public_schemas_are_valid_and_refs_resolve_locally(self) -> None:
        for name, schema in self.schemas.items():
            with self.subTest(schema=name):
                self.jsonschema.Draft202012Validator.check_schema(schema)
        for path in sorted((FIXTURE_DIRECTORY / "valid").glob("*.json")):
            with self.subTest(path=path.name):
                self.assertEqual(self.errors_for(load_json(path)), [])

    def test_valid_fixtures_pass(self) -> None:
        paths = sorted((FIXTURE_DIRECTORY / "valid").glob("*.json"))
        self.assertEqual(len(paths), 3)
        self.assertEqual(
            {load_json(path)["schema"] for path in paths},
            set(TARGET_SCHEMAS),
        )
        for path in paths:
            with self.subTest(path=path.name):
                self.assertEqual(self.errors_for(load_json(path)), [])

    def test_invalid_fixtures_have_one_rejection(self) -> None:
        paths = sorted((FIXTURE_DIRECTORY / "invalid").glob("*.json"))
        self.assertEqual(len(paths), 9)
        counts = {identifier: 0 for identifier in TARGET_SCHEMAS}
        for path in paths:
            with self.subTest(path=path.name):
                document = load_json(path)
                counts[document["schema"]] += 1
                self.assertEqual(len(self.errors_for(document)), 1)
        self.assertEqual(set(counts.values()), {3})

    def test_evidence_fixture_digests_are_intentional(self) -> None:
        paths = sorted(FIXTURE_DIRECTORY.glob("*/*evidence*.json"))
        self.assertEqual(len(paths), 4)
        for path in paths:
            with self.subTest(path=path.name):
                errors = evidence_contract_errors(load_json(path))
                if path.name == "evidence-digest-mismatch.json":
                    self.assertEqual(
                        errors,
                        ["evidence_digest does not match canonical content"],
                    )
                else:
                    self.assertEqual(errors, [])

    def test_promotion_status_exactly_tracks_backend_gates(self) -> None:
        path = FIXTURE_DIRECTORY / "valid/ontology-promotion-evidence-v1.json"
        promotable = load_json(path)
        validator = self.validators["palimnex:ontology-promotion-evidence:v1"]
        validator.validate(promotable)

        held = copy.deepcopy(promotable)
        held["status"] = "held"
        held["backends"]["cache"]["gates"]["deterministic"] = False
        validator.validate(held)

        held["status"] = "promotable"
        self.assertTrue(list(validator.iter_errors(held)))

        all_green_held = copy.deepcopy(promotable)
        all_green_held["status"] = "held"
        self.assertTrue(list(validator.iter_errors(all_green_held)))


if __name__ == "__main__":
    unittest.main()
