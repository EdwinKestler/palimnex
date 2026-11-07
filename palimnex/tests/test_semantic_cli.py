"""evaluate-semantic-shadow CLI integration (ontology Phase 4)."""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from typing import Any
from unittest import mock

from palimnex import core, semantic, semantic_eval


def report(status: str) -> dict[str, Any]:
    return {"schema": "palimnex:semantic-shadow-evaluation:v1", "status": status,
            "gates": {"cohort_gain": status == "promotable"},
            "held_reasons": [] if status == "promotable" else ["cohort_gain"],
            "promotion_authorized": False, "retrieval_influence": False,
            "authority": "evidence_only", "authorizes_actions": False}


def run(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = core.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class EvaluateSemanticShadowCliTests(unittest.TestCase):
    def test_promotable_exits_zero_and_never_authorizes(self) -> None:
        with mock.patch.object(semantic_eval, "evaluate_semantic_shadow",
                               return_value=report("promotable")) as called:
            code, out, _ = run(["evaluate-semantic-shadow"])
        self.assertEqual(code, 0)
        self.assertEqual(called.call_args.args, (core.ROOT,))
        self.assertEqual(called.call_args.kwargs, {})
        document = json.loads(out)
        self.assertFalse(document["promotion_authorized"])
        self.assertFalse(document["retrieval_influence"])
        self.assertFalse(document["authorizes_actions"])

    def test_held_exits_two_and_still_prints(self) -> None:
        with mock.patch.object(semantic_eval, "evaluate_semantic_shadow", return_value=report("held")):
            code, out, _ = run(["evaluate-semantic-shadow"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["held_reasons"], ["cohort_gain"])

    def test_typed_refusal_exits_one_without_document(self) -> None:
        error = semantic_eval.SemanticEvaluationError("fixture_digest_mismatch", "cohort")
        with mock.patch.object(semantic_eval, "evaluate_semantic_shadow", side_effect=error):
            code, out, err = run(["evaluate-semantic-shadow"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["status"], "error")

    def test_missing_configuration_is_refused(self) -> None:
        with mock.patch.object(core, "config_present", return_value=False), \
                mock.patch.object(semantic_eval, "evaluate_semantic_shadow") as called:
            code, out, _ = run(["evaluate-semantic-shadow"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        called.assert_not_called()

    def test_options_are_not_accepted(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            core.main(["evaluate-semantic-shadow", "--limit", "3"])

    def test_semantic_v1_status_is_unchanged(self) -> None:
        status = semantic.semantic_status({})
        self.assertEqual(status["mode"], "disabled")
        self.assertFalse(status["retrieval_influence"])
        self.assertEqual(semantic.MIN_MRR_GAIN, 0.05)
        self.assertEqual(semantic.MAX_LATENCY_MULTIPLIER, 2.0)


if __name__ == "__main__":
    unittest.main()
