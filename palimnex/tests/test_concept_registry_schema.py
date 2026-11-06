from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from palimnex.durable import canonical_json
from palimnex.locators import SourceLocator, resolve_locator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRECTORY = ROOT / "palimnex/schemas"
FIXTURE_DIRECTORY = ROOT / "palimnex/tests/fixtures/concept_registry"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


class ConceptRegistrySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import jsonschema
        from referencing import Registry, Resource

        cls.jsonschema = jsonschema
        cls.schema = load_json(SCHEMA_DIRECTORY / "concept-registry.v1.schema.json")
        cls.locator_schema = load_json(SCHEMA_DIRECTORY / "source-locator.v1.schema.json")
        cls.registry = Registry().with_resources(
            (
                (schema["$id"], Resource.from_contents(schema))
                for schema in (cls.schema, cls.locator_schema)
            )
        )
        cls.validator = jsonschema.Draft202012Validator(
            cls.schema,
            registry=cls.registry,
        )

    def test_public_schemas_are_valid_and_refs_resolve_locally(self) -> None:
        self.jsonschema.Draft202012Validator.check_schema(self.locator_schema)
        self.jsonschema.Draft202012Validator.check_schema(self.schema)
        fixture = load_json(next(iter(sorted((FIXTURE_DIRECTORY / "valid").glob("*.json")))))
        self.validator.validate(fixture)

    def test_valid_fixtures_validate_and_have_canonical_digests(self) -> None:
        paths = sorted((FIXTURE_DIRECTORY / "valid").glob("*.json"))
        self.assertEqual(len(paths), 4)
        for path in paths:
            with self.subTest(path=path.name):
                document = load_json(path)
                self.validator.validate(document)
                digest_input = {
                    key: value for key, value in document.items() if key != "registry_digest"
                }
                actual = hashlib.sha256(canonical_json(digest_input)).hexdigest()
                self.assertEqual(document["registry_digest"], actual)

    def test_valid_fixture_source_bindings_are_current(self) -> None:
        for path in sorted((FIXTURE_DIRECTORY / "valid").glob("*.json")):
            document = load_json(path)
            for concept in document["concepts"]:
                for binding in concept["source_bindings"]:
                    with self.subTest(path=path.name, concept=concept["concept_id"]):
                        resolved = resolve_locator(
                            SourceLocator.from_dict(binding),
                            ROOT,
                            {},
                        )
                        self.assertIsInstance(resolved, bytes)

    def test_invalid_fixtures_are_rejected(self) -> None:
        paths = sorted((FIXTURE_DIRECTORY / "invalid").glob("*.json"))
        self.assertEqual(len(paths), 7)
        for path in paths:
            with self.subTest(path=path.name):
                document = load_json(path)
                self.assertTrue(list(self.validator.iter_errors(document)))

    def test_reconciled_concept_id_pattern(self) -> None:
        validator = self.jsonschema.Draft202012Validator(self.schema["$defs"]["conceptId"])
        validator.validate("concept.source_locator")
        for value in ("a__b", "A.b", "-x"):
            with self.subTest(value=value):
                with self.assertRaises(self.jsonschema.ValidationError):
                    validator.validate(value)


if __name__ == "__main__":
    unittest.main()
