"""evaluate-ontology-shadow CLI integration (ontology Phase 3)."""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from palimnex import core, ontology_eval

REPO = Path(__file__).resolve().parents[2]


def report(**gates: bool) -> dict[str, Any]:
    names = ("baseline_identical", "no_critical_regression", "no_case_regression", "no_new_forbidden",
             "abstention_not_regressed", "ambiguity_never_contributes", "channels_visible", "bounded")
    return {"schema": "palimnex:ontology-shadow-evaluation:v1",
            "gates": {name: gates.get(name, True) for name in names},
            "promotion_authorized": False, "retrieval_influence": False,
            "authority": "evidence_only", "authorizes_actions": False}


def run(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = core.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class EvaluateOntologyShadowCliTests(unittest.TestCase):
    def test_all_gates_pass_exits_zero_and_prints_report(self) -> None:
        with mock.patch.object(ontology_eval, "evaluate_ontology_shadow", return_value=report()) as called:
            code, out, _ = run(["evaluate-ontology-shadow", "--limit", "3"])
        self.assertEqual(code, 0)
        self.assertEqual(called.call_args.kwargs["limit"], 3)
        document = json.loads(out)
        self.assertFalse(document["promotion_authorized"])
        self.assertFalse(document["authorizes_actions"])

    def test_any_failing_gate_exits_two_and_still_prints(self) -> None:
        with mock.patch.object(ontology_eval, "evaluate_ontology_shadow",
                               return_value=report(no_case_regression=False)):
            code, out, _ = run(["evaluate-ontology-shadow"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["gates"]["no_case_regression"])

    def test_typed_error_exits_one_without_document(self) -> None:
        with mock.patch.object(ontology_eval, "evaluate_ontology_shadow",
                               side_effect=ValueError("cohort digest mismatch")):
            code, out, err = run(["evaluate-ontology-shadow"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["status"], "error")

    def test_missing_configuration_is_refused(self) -> None:
        with mock.patch.object(core, "config_present", return_value=False), \
                mock.patch.object(ontology_eval, "evaluate_ontology_shadow") as called:
            code, _, _ = run(["evaluate-ontology-shadow"])
        self.assertEqual(code, 1)
        called.assert_not_called()

    def test_search_and_explain_search_parsers_are_unchanged(self) -> None:
        parsed = core.parser().parse_args(["search", "query", "--limit", "4"])
        self.assertEqual((parsed.command, parsed.query, parsed.limit), ("search", "query", 4))
        parsed = core.parser().parse_args(["explain-search", "query"])
        self.assertEqual((parsed.limit, parsed.byte_budget, parsed.backend), (5, 8192, "local"))

    def test_cohort_is_excluded_from_the_source_index(self) -> None:
        config = json.loads((REPO / ".palimnex.json").read_text())
        self.assertIn("palimnex/evaluation/ontology-shadow.v1.json", config["exclude_paths"])


if __name__ == "__main__":
    unittest.main()
