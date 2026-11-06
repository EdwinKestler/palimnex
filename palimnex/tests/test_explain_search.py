"""explain-search CLI integration (ontology Phase 2, R10)."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from palimnex import core
from palimnex.concepts import canonical_registry_digest
from palimnex.coverage import validate_receipt
from palimnex.retrieval import retrieve_sources

REPO = Path(__file__).resolve().parents[2]
SCHEMAS = REPO / "palimnex/schemas"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
QUERY = "how does source binding verification work"
GUIDE = b"# Guide\n\nSource binding verification reopens current bytes.\n"


def schema_validator() -> Draft202012Validator:
    names = ("source-locator.v1", "concept-registry.v1", "retrieval-coverage.v1", "explain-search.v1")
    schemas = {name: json.loads((SCHEMAS / f"{name}.schema.json").read_text()) for name in names}
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return Draft202012Validator(schemas["explain-search.v1"], registry=registry)


class ExplainSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".palimnex.json").write_text(
            json.dumps({"project_slug": "fixture", "project_id": PROJECT_ID}), encoding="utf-8"
        )
        (self.root / "docs").mkdir()
        (self.root / "docs/guide.md").write_bytes(GUIDE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_registry(self, relative: str, *, kind: str = "approved_registry") -> None:
        raw = (self.root / "docs/guide.md").read_bytes()
        concept = {
            "concept_id": "concept.source_binding",
            "canonical_name": "Bound source check",
            "aliases": ["source binding verification"],
            "definition": "Reopening and digest-checking bound source bytes.",
            "source_bindings": [{
                "scheme": "repo", "source_id": "docs/guide.md",
                "version": hashlib.sha256(raw).hexdigest(),
                "range": {"unit": "bytes", "start": 0, "end": len(raw)},
                "digest": hashlib.sha256(raw).hexdigest(),
            }] if kind == "approved_registry" else [],
            "status": "approved" if kind == "approved_registry" else "candidate",
            "provenance": {"origin": "manual"},
        }
        document: dict[str, Any] = {
            "schema": "palimnex:concept-registry:v1",
            "project": {"project_slug": "fixture", "project_id": PROJECT_ID},
            "registry_version": 1, "registry_kind": kind, "concepts": [concept],
            "registry_digest": "0" * 64, "authority": "historical_only", "authorizes_actions": False,
        }
        document["registry_digest"] = canonical_registry_digest(document)
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document), encoding="utf-8")

    def direct_search(self) -> dict[str, Any]:
        return retrieve_sources(QUERY, root=self.root, limit=5, byte_budget=8192, client=None)

    def test_absent_default_registry_disables_coverage(self) -> None:
        document = core.explain_search(QUERY, root=self.root)
        self.assertEqual(document["coverage_state"], "registry_absent")
        self.assertIsNone(document["coverage"])
        self.assertEqual(document["registry"], {"path": core.DEFAULT_CONCEPT_REGISTRY, "source": "default"})
        self.assertEqual(document["search"], self.direct_search())
        schema_validator().validate(document)

    def test_default_registry_produces_valid_answerable_receipt(self) -> None:
        self.write_registry(core.DEFAULT_CONCEPT_REGISTRY)
        document = core.explain_search(QUERY, root=self.root)
        self.assertEqual(document["coverage_state"], "enabled")
        self.assertEqual(document["registry"]["source"], "default")
        receipt = document["coverage"]
        validate_receipt(receipt)
        self.assertEqual(receipt["status"], "answerable")
        self.assertEqual(document["search"], self.direct_search())
        self.assertNotIn(QUERY, json.dumps(receipt))
        schema_validator().validate(document)

    def test_explicit_registry_argument(self) -> None:
        self.write_registry("custom/registry.json")
        document = core.explain_search(QUERY, root=self.root, registry="custom/registry.json")
        self.assertEqual(document["registry"], {"path": "custom/registry.json", "source": "argument"})
        self.assertEqual(document["coverage"]["status"], "answerable")

    def test_explicit_missing_registry_is_an_error_not_absent(self) -> None:
        with self.assertRaises(ValueError):
            core.explain_search(QUERY, root=self.root, registry="custom/missing.json")

    def test_unsafe_registry_arguments_are_refused(self) -> None:
        for argument in ("../outside.json", "/etc/passwd", "a/../../b.json", "", "a\\b.json"):
            with self.subTest(argument=argument), self.assertRaises(ValueError) as caught:
                core.concept_registry_selection(argument)
            self.assertNotIn("passwd", str(caught.exception))

    def test_candidate_registry_is_refused(self) -> None:
        self.write_registry(core.DEFAULT_CONCEPT_REGISTRY, kind="candidate_set")
        with self.assertRaises(ValueError):
            core.explain_search(QUERY, root=self.root)

    def test_search_result_is_not_mutated(self) -> None:
        self.write_registry(core.DEFAULT_CONCEPT_REGISTRY)
        before = self.direct_search()
        snapshot = copy.deepcopy(before)
        core.explain_search(QUERY, root=self.root)
        self.assertEqual(before, snapshot)

    def test_missing_configuration_is_refused(self) -> None:
        (self.root / ".palimnex.json").unlink()
        with self.assertRaises(ValueError):
            core.explain_search(QUERY, root=self.root)

    def test_cli_on_repository_without_registry(self) -> None:
        if (REPO / core.DEFAULT_CONCEPT_REGISTRY).exists():
            self.skipTest("repository now carries an approved registry")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = core.main(["explain-search", "concept registry", "--limit", "2"])
        self.assertEqual(code, 0)
        document = json.loads(stdout.getvalue())
        self.assertEqual(document["schema"], "palimnex:explain-search:v1")
        self.assertEqual(document["coverage_state"], "registry_absent")
        schema_validator().validate(document)

    def test_cli_refusal_is_non_echoing_and_nonzero(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = core.main(["explain-search", "concept", "--registry", "../secret-name.json"])
        self.assertEqual(code, 1)
        self.assertNotIn("secret-name", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
