from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from palimnex.concepts import (
    ConceptRegistry,
    ConceptRegistryError,
    match_aliases,
    parse_registry,
    verify_source_bindings,
)
from palimnex.locators import ResolvedSource


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "palimnex/tests/fixtures/ontology/cases.v0.json"
SCHEMA_DIRECTORY = ROOT / "palimnex/schemas"
REGISTRY_FIXTURE_DIRECTORY = ROOT / "palimnex/tests/fixtures/concept_registry"
MATRIX_SHA256 = "a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b"
COVERAGE_STATUSES = frozenset({"answerable", "partial", "ambiguous", "unanswerable"})


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


class ForeignProjectResolver:
    api_version = 1

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def resolve(self, source_id: str, version: str) -> ResolvedSource:
        raise AssertionError("a foreign-project resolver must be refused before use")


class FrozenConceptConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import jsonschema
        from referencing import Registry, Resource

        cls.matrix = load_json_object(MATRIX_PATH)
        cls.registry_schema = load_json_object(
            SCHEMA_DIRECTORY / "concept-registry.v1.schema.json"
        )
        locator_schema = load_json_object(
            SCHEMA_DIRECTORY / "source-locator.v1.schema.json"
        )
        registry = Registry().with_resources(
            (
                (schema["$id"], Resource.from_contents(schema))
                for schema in (cls.registry_schema, locator_schema)
            )
        )
        cls.schema_validator = jsonschema.Draft202012Validator(
            cls.registry_schema,
            registry=registry,
        )

    def test_frozen_matrix_digest(self) -> None:
        self.assertEqual(
            hashlib.sha256(MATRIX_PATH.read_bytes()).hexdigest(),
            MATRIX_SHA256,
        )

    def test_every_phase_1_frozen_case(self) -> None:
        cases = [case for case in self.matrix["cases"] if case["gates_phase"] == 1]
        self.assertEqual(len(cases), 15)
        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                self._assert_phase_1_case(case)

    def test_runtime_and_schema_parity_for_every_frozen_registry(self) -> None:
        checked = 0
        for case in self.matrix["cases"]:
            for fixture_key in ("registry_fixture", "candidate_registry_fixture"):
                document = case.get(fixture_key)
                if document is None:
                    continue
                checked += 1
                with self.subTest(case_id=case["case_id"], fixture=fixture_key):
                    self._assert_validator_parity(
                        document,
                        allow_placeholder_digests=bool(
                            case.get("binding_digests_are_placeholders", False)
                        ),
                    )
        self.assertEqual(checked, 30)

    def test_runtime_and_schema_parity_for_schema_lane_fixtures(self) -> None:
        paths = sorted(REGISTRY_FIXTURE_DIRECTORY.glob("*/*.json"))
        self.assertEqual(len(paths), 11)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self._assert_validator_parity(
                    load_json_object(path),
                    allow_placeholder_digests=False,
                )

    def _assert_phase_1_case(self, case: dict[str, Any]) -> None:
        self.assertIn(case["expected_status"], COVERAGE_STATUSES)
        self.assertTrue(
            set(case["expected_ambiguous_concept_ids"]).isdisjoint(
                case["expected_covered_concept_ids"]
            )
        )
        document = case["registry_fixture"]
        allow_placeholders = bool(case.get("binding_digests_are_placeholders", False))

        if case["case_id"] == "ONT-CROSS-001":
            with self.assertRaises(ConceptRegistryError) as raised:
                parse_registry(
                    document,
                    root=ROOT,
                    allow_placeholder_digests=allow_placeholders,
                )
            self.assertEqual(raised.exception.reason, "project_mismatch")
            self.assertEqual(case["expected_outcome"], "error")
            self.assertEqual(case["expected_recognized_concept_ids"], [])
            self.assertEqual(case["expected_ambiguous_concept_ids"], [])
            self._assert_no_echo(
                raised.exception,
                tuple(str(value) for value in document["project"].values()),
            )
            return

        registry = parse_registry(
            document,
            root=ROOT,
            allow_placeholder_digests=allow_placeholders,
        )
        self.assertIsInstance(registry, ConceptRegistry)

        if case["category"] == "secret":
            recipe = case["canary_recipe"]
            self.assertEqual(recipe["operation"], "join")
            canary = "".join(tuple(recipe["fragments"]))
            with self.assertRaises(ConceptRegistryError) as raised:
                match_aliases(registry, canary)
            self.assertEqual(raised.exception.reason, "query_privacy_refused")
            self.assertEqual(case["expected_outcome"], "error")
            self.assertEqual(case["expected_recognized_concept_ids"], [])
            self.assertEqual(case["expected_ambiguous_concept_ids"], [])
            self._assert_no_echo(raised.exception, (canary,))
            return

        result = match_aliases(registry, case["query"])
        self.assertEqual(
            result.recognized_concept_ids,
            tuple(case["expected_recognized_concept_ids"]),
        )
        self.assertEqual(
            result.ambiguous_concept_ids,
            tuple(case["expected_ambiguous_concept_ids"]),
        )

        if case["expected_outcome"] == "receipt":
            return

        self.assertEqual(case["expected_outcome"], "error")
        with self.assertRaises(ConceptRegistryError) as raised:
            self._verify_expected_refusal(case, registry)
        expected_reasons = {
            "ONT-PATH-001": "source_path_refused",
            "ONT-PATH-002": "source_symlink_refused",
            "ONT-CROSS-002": "source_project_mismatch",
        }
        self.assertEqual(raised.exception.reason, expected_reasons[case["case_id"]])
        rejected_values = tuple(
            binding["source_id"]
            for concept in document["concepts"]
            for binding in concept["source_bindings"]
        )
        self._assert_no_echo(raised.exception, rejected_values)

    def _verify_expected_refusal(
        self,
        case: dict[str, Any],
        registry: ConceptRegistry,
    ) -> None:
        if case["case_id"] == "ONT-PATH-002":
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".palimnex.json").write_text(
                    json.dumps(case["registry_fixture"]["project"]),
                    encoding="utf-8",
                )
                target = root / "target"
                target.mkdir()
                (target / "source.txt").write_bytes(b"fixture\n")
                (root / "linked").symlink_to(target, target_is_directory=True)
                verify_source_bindings(registry, root=root)
            return

        if case["case_id"] == "ONT-CROSS-002":
            foreign_case = next(
                item for item in self.matrix["cases"] if item["case_id"] == "ONT-CROSS-001"
            )
            foreign_id = foreign_case["registry_fixture"]["project"]["project_id"]
            verify_source_bindings(
                registry,
                root=ROOT,
                resolvers={"fixture": ForeignProjectResolver(foreign_id)},
            )
            return

        verify_source_bindings(registry, root=ROOT)

    def _assert_validator_parity(
        self,
        document: dict[str, Any],
        *,
        allow_placeholder_digests: bool,
    ) -> None:
        schema_accepts = not list(self.schema_validator.iter_errors(document))
        runtime_accepts, runtime_reason = self._runtime_accepts(
            document,
            allow_placeholder_digests=allow_placeholder_digests,
        )
        self.assertEqual(
            runtime_accepts,
            schema_accepts,
            f"runtime reason: {runtime_reason}",
        )

    def _runtime_accepts(
        self,
        document: dict[str, Any],
        *,
        allow_placeholder_digests: bool,
    ) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = document.get("project")
            if isinstance(project, dict):
                (root / ".palimnex.json").write_text(
                    json.dumps(project),
                    encoding="utf-8",
                )
            try:
                parse_registry(
                    document,
                    root=root,
                    allow_placeholder_digests=allow_placeholder_digests,
                )
            except ConceptRegistryError as exc:
                return False, exc.reason
        return True, "accepted"

    def _assert_no_echo(
        self,
        error: ConceptRegistryError,
        rejected_values: tuple[str, ...],
    ) -> None:
        rendered = str(error)
        for value in rejected_values:
            self.assertNotIn(value, rendered)


if __name__ == "__main__":
    unittest.main()
