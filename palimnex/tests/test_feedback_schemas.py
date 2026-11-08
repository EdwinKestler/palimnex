from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from palimnex.security import scan_bytes


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRECTORY = ROOT / "palimnex/schemas"
FIXTURE_DIRECTORY = ROOT / "palimnex/tests/fixtures/retrieval_feedback"
SCHEMA_NAMES = (
    "retrieval-feedback.v1.schema.json",
    "retrieval-feedback-withdrawal.v1.schema.json",
    "retrieval-feedback-report.v1.schema.json",
)
TARGET_SCHEMAS = {
    "palimnex:retrieval-feedback:v1": "retrieval-feedback.v1.schema.json",
    "palimnex:retrieval-feedback-withdrawal:v1": (
        "retrieval-feedback-withdrawal.v1.schema.json"
    ),
    "palimnex:retrieval-feedback-report:v1": (
        "retrieval-feedback-report.v1.schema.json"
    ),
}
EXISTING_SCHEMA_DIGESTS = {
    "audit-graph.v1.schema.json": "5a8fd782dab9f5944e34246eb59dba998a8468e71bc0f3c486183932d464f78c",
    "cleanup-plan.v1.schema.json": "0286ca5908f0b63b47afb6306a74a9542374d1643f30c21ef0ffc12317bf63fc",
    "cleanup-plan.v2.schema.json": "a0cc5872b276d6f3ab5b8f0d61090991b3db1e56547eae7661ebf739dfbcc46e",
    "concept-registry.v1.schema.json": "553ffe3823f7513b6b5ee00f5ab54e520fb9abb23570c1cd8a6537925d8e3e35",
    "context.v2.schema.json": "97b20549bf32f076780d548311d15d50765c7f3b82a87b612941345717add863",
    "deletion-contract.v1.schema.json": "2e01ad1a09d8eb837c1b5324a3f1ad72f81df12baf367a7f4d0726d8e7888f0a",
    "deletion-contract.v2.schema.json": "296d91e0c1d72c934a2105ef4343c46812e01927f97f1bf208e49e4fcc6b2523",
    "erasure-tombstone.v1.schema.json": "7e82ed7d5b4ba7cb1fa35055023d50cd3c51413d4fef3d6de9c207f1e3913d2f",
    "event-checkpoint.v1.schema.json": "eb08288ba0b56fa07141ceac45742742e892dd8d1575d5925f95a12856f92649",
    "explain-search.v1.schema.json": "924ea9d2c255f3d4264bfe6724b2034c8d08c53e2151a985d4aea9991c3fc9f6",
    "explain-search.v2.schema.json": "e0b2fd69cf16cc734e21e4300d0e4b6d6db2ee5509c96c8c8a4fba396eaef79a",
    "logical-export.v1.schema.json": "fe42b7c25f2ad9ffc3ddf01e306b32446ac4a6dfd29f051cb38598fc6117fda1",
    "memory-event.v1.schema.json": "3e2bd84a8067f2a03b79df5ba13761893ba98d61039a35425970020c8b1257a9",
    "memory-pack-manifest.v2.schema.json": "1534c46f00fe94c610ca365137421bdbae5427689365ad77057b09bb1fb94bad",
    "ontology-promotion-evidence.v1.schema.json": "d8dea49647e7f35eca4f41d812954c3ce57cbca285e0448df756346de8276de1",
    "ontology-shadow-comparison.v1.schema.json": "37f20db889dc3fbd6d937901c1bba6d9beb451b25a5aa7e21cb4eedc825bfafd",
    "retention-policy.v1.schema.json": "5af70865bfb43018288aa60b1399e959f2a4de95cab09c6cc0bdffee770c9b50",
    "retrieval-coverage.v1.schema.json": "b47ae60107bd9ceeaec491070a94dc26e3e6663248399d88a4007c517f08d206",
    "semantic-provider-identity.v1.schema.json": "0e1d69b47f8ee1730aaf640daa8f2e5b94cfc6bde1747e8cf83808edf781bc6f",
    "semantic-shadow-cohort.v1.schema.json": "e9d98e6565e03ed7d41e464dfa73beca6bc540482ed9b355408844f6a71a5105",
    "semantic-shadow-comparison.v1.schema.json": "6474da89917c33461283c26b75f2d51d767122b0be869629f5f7ce0516b8c76c",
    "semantic-shadow-evaluation.v1.schema.json": "a77b282ba2144f9f5ff2105738f552ed5c9fea1c9c720755130c694ffdd0c75b",
    "signature.v1.schema.json": "081c2ad13d9af2a97ef7e492ed20d6225e6f189aec21e4528773994114dd1e90",
    "source-locator.v1.schema.json": "7a2048488cd962e39ddd7915fa2bd3fe4376021cc18987b77a850d896f66d22e",
    "workflow-spec.v1.schema.json": "94aaca7f536a27452d362ee6015911c35a3c24029058c8d9da16408d65f03721",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def feedback_contract_errors(document: dict[str, Any]) -> list[str]:
    if document.get("schema") != "palimnex:retrieval-feedback:v1":
        return []
    source = document.get("source")
    if not isinstance(source, dict):
        return []
    start_line = source.get("start_line")
    end_line = source.get("end_line")
    if (
        type(start_line) is int
        and type(end_line) is int
        and start_line > end_line
    ):
        return ["source.end_line must be greater than or equal to start_line"]
    return []


def object_schemas(value: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            if current.get("type") == "object":
                found.append(current)
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return found


class FeedbackSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import jsonschema
        from referencing import Registry, Resource

        cls.jsonschema = jsonschema
        cls.schemas = {
            name: load_json(SCHEMA_DIRECTORY / name) for name in SCHEMA_NAMES
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
        validator = self.validators.get(document.get("schema"))
        if validator is None:
            return ["unknown fixture schema"]
        errors = [error.message for error in validator.iter_errors(document)]
        if not errors:
            errors.extend(feedback_contract_errors(document))
        return errors

    def test_public_schemas_are_valid_and_resolve_from_local_registry(self) -> None:
        for name, schema in self.schemas.items():
            with self.subTest(schema=name):
                self.jsonschema.Draft202012Validator.check_schema(schema)
                self.assertIsNotNone(self.registry.get(schema["$id"]))

    def test_schema_ids_are_unique_across_public_schemas(self) -> None:
        identifiers = [
            load_json(path)["$id"]
            for path in sorted(SCHEMA_DIRECTORY.glob("*.schema.json"))
        ]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_every_object_schema_rejects_additional_properties(self) -> None:
        for name, schema in self.schemas.items():
            objects = object_schemas(schema)
            self.assertTrue(objects)
            for index, object_schema in enumerate(objects):
                with self.subTest(schema=name, object_index=index):
                    self.assertIs(object_schema.get("additionalProperties"), False)

    def test_valid_fixtures_pass(self) -> None:
        paths = sorted((FIXTURE_DIRECTORY / "valid").glob("*.json"))
        self.assertEqual(len(paths), 3)
        self.assertEqual(
            {load_json(path)["schema"] for path in paths}, set(TARGET_SCHEMAS)
        )
        for path in paths:
            with self.subTest(path=path.name):
                self.assertEqual(self.errors_for(load_json(path)), [])

    def test_report_fixture_covers_every_state(self) -> None:
        report = load_json(FIXTURE_DIRECTORY / "valid/retrieval-feedback-report-v1.json")
        states = {record["state"] for record in report["records"]}
        self.assertEqual(
            states, {"current", "stale", "superseded", "withdrawn", "invalid"}
        )
        self.assertEqual(report["counts"], {state: 1 for state in states})

    def test_invalid_fixtures_each_have_one_rejection(self) -> None:
        paths = sorted((FIXTURE_DIRECTORY / "invalid").glob("*.json"))
        self.assertEqual(len(paths), 7)
        expected_rules = {
            "bad-digest.json",
            "end-before-start.json",
            "extra-key.json",
            "missing-field.json",
            "oversized-note.json",
            "unknown-judgement.json",
            "wrong-constant.json",
        }
        self.assertEqual({path.name for path in paths}, expected_rules)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertEqual(len(self.errors_for(load_json(path))), 1)

    def test_fixture_bytes_have_no_privacy_findings(self) -> None:
        paths = sorted(FIXTURE_DIRECTORY.glob("*/*.json"))
        self.assertEqual(len(paths), 10)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertEqual(scan_bytes(path.read_bytes()), [])

    def test_existing_public_schemas_are_byte_unchanged(self) -> None:
        actual_names = {
            path.name
            for path in SCHEMA_DIRECTORY.glob("*.schema.json")
            if path.name not in SCHEMA_NAMES
        }
        self.assertEqual(actual_names, set(EXISTING_SCHEMA_DIGESTS))
        for name, expected_digest in EXISTING_SCHEMA_DIGESTS.items():
            with self.subTest(schema=name):
                actual_digest = hashlib.sha256(
                    (SCHEMA_DIRECTORY / name).read_bytes()
                ).hexdigest()
                self.assertEqual(actual_digest, expected_digest)


if __name__ == "__main__":
    unittest.main()
