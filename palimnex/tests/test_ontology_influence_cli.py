"""Influence CLI integration: ontology-status, evaluate-ontology-promotion, explain-search v2."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from palimnex import core, ontology_influence, ontology_promotion, retrieval
from palimnex.ontology_influence import InfluenceSetting, OntologyInfluenceError

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
DISCLOSURE = {
    "mode": "enabled", "channel": "ontology", "retrieval_influence": True,
    "registry_digest": "a" * 64, "promotion_evidence_digest": "b" * 64,
    "implementation_digest": "c" * 64, "contributing_concept_ids": ["concept.source_binding"],
}


def run(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = core.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def validator(name: str) -> Draft202012Validator:
    schemas = [json.loads(p.read_text()) for p in SCHEMAS.glob("*.schema.json")]
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    return Draft202012Validator(json.loads((SCHEMAS / f"{name}.schema.json").read_text()), registry=registry)


def enabled_setting() -> InfluenceSetting:
    return InfluenceSetting("enabled", "ontology/concept-registry.v1.json", "a" * 64,
                            "artifacts/promotion.json", "b" * 64)


class OntologyStatusTests(unittest.TestCase):
    def test_repository_default_is_off_and_exits_zero(self) -> None:
        code, out, _ = run(["ontology-status"])
        document = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(document["mode"], "off")
        self.assertFalse(document["retrieval_influence"])
        self.assertFalse(document["authorizes_actions"])

    def test_enabled_but_refused_exits_two_with_reason(self) -> None:
        with mock.patch.object(ontology_influence, "read_influence_setting", return_value=enabled_setting()), \
                mock.patch.object(ontology_influence, "activate_influence",
                                  side_effect=OntologyInfluenceError("registry_stale", "registry")):
            code, out, _ = run(["ontology-status"])
        document = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual((document["activation"], document["reason"]), ("refused", "registry_stale"))
        self.assertFalse(document["retrieval_influence"])

    def test_enabled_and_ready_exits_zero(self) -> None:
        with mock.patch.object(ontology_influence, "read_influence_setting", return_value=enabled_setting()), \
                mock.patch.object(ontology_influence, "activate_influence", return_value=object()):
            code, out, _ = run(["ontology-status"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["activation"], "ready")

    def test_malformed_setting_exits_one(self) -> None:
        with mock.patch.object(ontology_influence, "read_influence_setting",
                               side_effect=OntologyInfluenceError("setting_invalid")):
            code, out, err = run(["ontology-status"])
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["status"], "error")


class PromotionCliTests(unittest.TestCase):
    def evidence(self, status: str) -> dict[str, Any]:
        return {"schema": "palimnex:ontology-promotion-evidence:v1", "status": status,
                "activation_authorized": False, "authorizes_actions": False}

    def test_promotable_exits_zero_and_never_writes(self) -> None:
        with mock.patch.object(ontology_promotion, "evaluate_ontology_promotion",
                               return_value=self.evidence("promotable")) as called:
            code, out, _ = run(["evaluate-ontology-promotion", "--limit", "3", "--registry", "custom/reg.json"])
        self.assertEqual(code, 0)
        self.assertEqual(called.call_args.kwargs, {"registry_path": "custom/reg.json", "limit": 3})
        self.assertFalse(json.loads(out)["activation_authorized"])

    def test_held_exits_two(self) -> None:
        with mock.patch.object(ontology_promotion, "evaluate_ontology_promotion",
                               return_value=self.evidence("held")):
            code, _, _ = run(["evaluate-ontology-promotion"])
        self.assertEqual(code, 2)

    def test_missing_registry_error_exits_one(self) -> None:
        with mock.patch.object(ontology_promotion, "evaluate_ontology_promotion",
                               side_effect=ValueError("registry missing")):
            code, out, _ = run(["evaluate-ontology-promotion"])
        self.assertEqual((code, out), (1, ""))

    def test_unsafe_registry_argument_is_refused(self) -> None:
        with mock.patch.object(ontology_promotion, "evaluate_ontology_promotion") as called:
            code, _, _ = run(["evaluate-ontology-promotion", "--registry", "../outside.json"])
        self.assertEqual(code, 1)
        called.assert_not_called()


class ExplainSearchV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".palimnex.json").write_text(
            json.dumps({"project_slug": "fixture", "project_id": PROJECT_ID}), encoding="utf-8")
        (self.root / "docs").mkdir()
        (self.root / "docs/guide.md").write_text("# Guide\n\nSource binding verification.\n", encoding="utf-8")
        self.real = retrieval.retrieve_sources

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_uninfluenced_result_stays_v1(self) -> None:
        document = core.explain_search("source binding verification", root=self.root)
        self.assertEqual(document["schema"], "palimnex:explain-search:v1")
        self.assertNotIn("ranking_influence", document)

    def test_influenced_result_is_disclosed_as_v2(self) -> None:
        def influenced(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {**self.real(*args, **kwargs), "ontology_influence": dict(DISCLOSURE)}

        with mock.patch.object(retrieval, "retrieve_sources", side_effect=influenced):
            document = core.explain_search("source binding verification", root=self.root)
        self.assertEqual(document["schema"], "palimnex:explain-search:v2")
        self.assertEqual(document["ranking_influence"], DISCLOSURE)
        self.assertEqual(document["coverage_state"], "registry_absent")
        validator("explain-search.v2").validate(document)


if __name__ == "__main__":
    unittest.main()
