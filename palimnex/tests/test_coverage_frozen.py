from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from palimnex.concepts import canonical_registry_digest, parse_registry
from palimnex.coverage import (
    CoverageError,
    build_coverage_receipt,
    build_explain_search,
    validate_receipt,
)
from palimnex.durable import canonical_json
from palimnex.locators import SourceRange, select_range


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "palimnex/tests/fixtures/ontology/cases.v0.json"
SCHEMA_DIRECTORY = ROOT / "palimnex/schemas"
COVERAGE_FIXTURE_DIRECTORY = ROOT / "palimnex/tests/fixtures/retrieval_coverage"
MATRIX_SHA256 = "a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b"
SYNTHETIC_RETRIEVAL_LIMIT = 1
SCHEMA_NAMES = (
    "concept-registry.v1.schema.json",
    "source-locator.v1.schema.json",
    "retrieval-coverage.v1.schema.json",
    "explain-search.v1.schema.json",
)


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def coverage_contract_errors(document: Mapping[str, Any]) -> list[str]:
    """Return accepted cross-field errors that JSON Schema cannot express."""
    errors: list[str] = []
    coverage = document.get("coverage")
    if not isinstance(coverage, dict):
        return ["coverage must be an object"]
    for name in ("numerator", "denominator"):
        if type(coverage.get(name)) is not int:
            errors.append(f"coverage.{name} must be a JSON integer")

    try:
        covered = {
            item["concept_id"] for item in document["covered_concepts"]["items"]
        }
        uncovered = set(document["uncovered_concepts"]["items"])
        stale = {
            item["concept_id"] for item in document["stale_concepts"]["items"]
        }
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
        if document.get("receipt_digest") != actual_digest:
            errors.append("receipt_digest does not match canonical content")
    except (KeyError, TypeError, ValueError):
        errors.append("coverage cross-field structure is invalid")
    return errors


class FrozenCoverageConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import jsonschema
        from referencing import Registry, Resource

        cls.matrix = load_json_object(MATRIX_PATH)
        cls.schemas = {
            name: load_json_object(SCHEMA_DIRECTORY / name) for name in SCHEMA_NAMES
        }
        registry = Registry().with_resources(
            (
                (schema["$id"], Resource.from_contents(schema))
                for schema in cls.schemas.values()
            )
        )
        cls.coverage_validator = jsonschema.Draft202012Validator(
            cls.schemas["retrieval-coverage.v1.schema.json"],
            registry=registry,
        )
        cls.explain_validator = jsonschema.Draft202012Validator(
            cls.schemas["explain-search.v1.schema.json"],
            registry=registry,
        )

    def test_frozen_matrix_digest(self) -> None:
        self.assertEqual(
            hashlib.sha256(MATRIX_PATH.read_bytes()).hexdigest(),
            MATRIX_SHA256,
        )

    def test_every_phase_2_frozen_case(self) -> None:
        cases = [case for case in self.matrix["cases"] if case["gates_phase"] == 2]
        self.assertEqual(len(cases), 12)
        self.assertEqual(
            sum(bool(case.get("expected_status_disputed")) for case in cases),
            2,
        )
        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                self._assert_phase_2_case(case)

    def test_runtime_and_schema_parity_for_schema_lane_fixtures(self) -> None:
        paths = sorted(COVERAGE_FIXTURE_DIRECTORY.glob("*/*.json"))
        self.assertEqual(len(paths), 19)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                document = load_json_object(path)
                schema_accepts = self._schema_contract_accepts(document)
                runtime_accepts = self._runtime_accepts(document)
                self.assertEqual(runtime_accepts, schema_accepts)
                self.assertEqual(schema_accepts, path.parent.name == "valid")

    def _assert_phase_2_case(self, case: dict[str, Any]) -> None:
        self.assertEqual(case["expected_outcome"], "receipt")
        self.assertTrue(case["binding_digests_are_placeholders"])
        if case.get("expected_status_disputed"):
            self.assertEqual(case["category"], "stale-source")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = copy.deepcopy(case["registry_fixture"])
            (root / ".palimnex.json").write_text(
                json.dumps(document["project"]),
                encoding="utf-8",
            )
            self._materialize_bindings(case, document, root)
            document["registry_digest"] = canonical_registry_digest(document)
            registry = parse_registry(document, root=root)
            search = self._search_result(case, root)
            receipt = build_coverage_receipt(
                registry,
                case["query"],
                search,
                root=root,
                retrieval_limit=SYNTHETIC_RETRIEVAL_LIMIT,
            )

            self.assertEqual(receipt["status"], case["expected_status"])
            self.assertEqual(
                self._concept_ids(receipt["recognized_concepts"]),
                set(case["expected_recognized_concept_ids"]),
            )
            self.assertEqual(
                self._concept_ids(receipt["covered_concepts"]),
                set(case["expected_covered_concept_ids"]),
            )
            self.assertEqual(
                set(receipt["uncovered_concepts"]["items"]),
                set(case["expected_uncovered_concept_ids"]),
            )
            self.assertEqual(
                self._concept_ids(receipt["stale_concepts"]),
                set(case["expected_stale_concept_ids"]),
            )
            self.assertEqual(
                self._ambiguous_ids(receipt["ambiguous_concepts"]),
                set(case["expected_ambiguous_concept_ids"]),
            )
            self._assert_retrieval_condition(case, receipt)

            validate_receipt(receipt)
            self.assertTrue(self._schema_contract_accepts(receipt))
            explained = build_explain_search(
                search,
                receipt,
                registry_path="ontology/concept-registry.v1.json",
                registry_source="default",
            )
            self.explain_validator.validate(explained)

    def _materialize_bindings(
        self,
        case: dict[str, Any],
        document: dict[str, Any],
        root: Path,
    ) -> None:
        bindings = [
            binding
            for concept in document["concepts"]
            for binding in concept["source_bindings"]
        ]
        by_path: dict[str, list[dict[str, Any]]] = {}
        for binding in bindings:
            self.assertEqual(
                binding["digest"],
                self.matrix["placeholder_locator_digest"],
            )
            by_path.setdefault(binding["source_id"], []).append(binding)

        source_bytes: dict[str, bytes] = {}
        for source_id, path_bindings in by_path.items():
            raw = self._source_bytes(path_bindings)
            target = root / source_id
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            source_bytes[source_id] = raw

        for binding in bindings:
            raw = source_bytes[binding["source_id"]]
            bounds = SourceRange(**binding["range"])
            selected = select_range(raw, bounds)
            self.assertTrue(selected)
            binding["digest"] = hashlib.sha256(selected).hexdigest()
            if binding["scheme"] == "repo":
                binding["version"] = hashlib.sha256(raw).hexdigest()

        case_id = case["case_id"]
        if case_id == "ONT-STALE-001":
            binding = bindings[0]
            target = root / binding["source_id"]
            drifted = self._drift_selected_bytes(
                source_bytes[binding["source_id"]],
                SourceRange(**binding["range"]),
            )
            target.write_bytes(drifted)
            binding["version"] = hashlib.sha256(drifted).hexdigest()
        elif case_id == "ONT-STALE-002":
            binding = bindings[0]
            target = root / binding["source_id"]
            target.write_bytes(source_bytes[binding["source_id"]] + b"version drift\n")

    def _source_bytes(self, bindings: list[dict[str, Any]]) -> bytes:
        line_end = max(
            (
                binding["range"]["end"]
                for binding in bindings
                if binding["range"]["unit"] == "lines"
            ),
            default=0,
        )
        byte_end = max(
            (
                binding["range"]["end"]
                for binding in bindings
                if binding["range"]["unit"] == "bytes"
            ),
            default=0,
        )
        if line_end:
            raw = "".join(
                f"admissible fixture line {line_number:04d}\n"
                for line_number in range(1, line_end + 1)
            ).encode("utf-8")
            if len(raw) >= byte_end:
                return raw
        return b"x" * max(byte_end, 1)

    def _drift_selected_bytes(self, raw: bytes, bounds: SourceRange) -> bytes:
        if bounds.unit == "bytes":
            drifted = bytearray(raw)
            drifted[bounds.start] = ord("y") if drifted[bounds.start] != ord("y") else ord("z")
            return bytes(drifted)
        lines = raw.decode("utf-8").splitlines()
        lines[bounds.start - 1] += " changed"
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _search_result(self, case: dict[str, Any], root: Path) -> dict[str, Any]:
        is_truncated = case["category"] == "truncation"
        is_budget_omission = case["category"] == "byte-budget"
        omitted = 1 if is_truncated or is_budget_omission else 0
        byte_budget = 2 if is_budget_omission else 8192
        results = [{}] if is_truncated else []
        return {
            "query": case["query"],
            "results": results,
            "candidate_count": len(results) + omitted,
            "omitted_count": omitted,
            "byte_budget": byte_budget,
            "items_bytes": 4 if results else 2,
            "budget_unit": "serialized_utf8_bytes",
            "cache_consulted": False,
            "retrieval_mode": "local_snapshot_rrf",
            "scan_scope": "full_admitted_corpus",
            "corpus_fingerprint": "c" * 64,
            "checkout_id": hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest(),
            "semantic_influence": False,
            "authorizes_actions": False,
        }

    def _assert_retrieval_condition(
        self,
        case: dict[str, Any],
        receipt: dict[str, Any],
    ) -> None:
        state = receipt["retrieval_state"]
        self.assertEqual(
            state["retrieval_truncated"],
            case["category"] == "truncation",
        )
        self.assertEqual(
            state["byte_budget_omission"]["omitted"],
            case["category"] == "byte-budget",
        )

    def _schema_contract_accepts(self, document: dict[str, Any]) -> bool:
        schema = document.get("schema")
        if schema == "palimnex:retrieval-coverage:v1":
            return not list(self.coverage_validator.iter_errors(document)) and not coverage_contract_errors(
                document
            )
        if schema == "palimnex:explain-search:v1":
            if list(self.explain_validator.iter_errors(document)):
                return False
            coverage = document.get("coverage")
            return coverage is None or not coverage_contract_errors(coverage)
        return False

    def _runtime_accepts(self, document: dict[str, Any]) -> bool:
        try:
            if document.get("schema") == "palimnex:retrieval-coverage:v1":
                validate_receipt(document)
                return True
            if document.get("schema") != "palimnex:explain-search:v1":
                return False
            registry = document["registry"]
            rebuilt = build_explain_search(
                document["search"],
                document["coverage"],
                registry_path=registry["path"],
                registry_source=registry["source"],
            )
            return rebuilt == document
        except (CoverageError, KeyError, TypeError, ValueError):
            return False

    def _concept_ids(self, collection: dict[str, Any]) -> set[str]:
        return {item["concept_id"] for item in collection["items"]}

    def _ambiguous_ids(self, collection: dict[str, Any]) -> set[str]:
        return {
            concept_id
            for item in collection["items"]
            for concept_id in item["candidate_concept_ids"]
        }


if __name__ == "__main__":
    unittest.main()
