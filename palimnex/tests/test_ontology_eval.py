from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from palimnex import cache_v3
from palimnex._offline_fixtures import write_project
from palimnex.ontology_eval import (
    EVALUATION_SCHEMA,
    OntologyEvaluationError,
    _CaseOutcome,
    _EvaluationCase,
    _VariantOutcome,
    _load_cohort_document,
    _materialize_registry,
    _metric_summary,
    _gates,
    _run_case,
    _suite_report,
    evaluate_ontology_shadow,
)
from palimnex.retrieval import shadow_retrieve


class OntologyShadowEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]
        cls.first_report = evaluate_ontology_shadow(cls.root)
        cls.second_report = evaluate_ontology_shadow(cls.root)

    def test_real_report_is_deterministic_structured_and_non_authorizing(self) -> None:
        report = self.first_report
        self.assertEqual(report, self.second_report)
        self.assertEqual(report["schema"], EVALUATION_SCHEMA)
        self.assertRegex(report["cohort_digest"], r"^[0-9a-f]{64}$")
        self.assertRegex(report["registry_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(set(report["suites"]), {"v27", "challenges_v26", "cohort"})
        self.assertEqual(report["suites"]["v27"]["baseline"]["case_count"], 13)
        self.assertEqual(report["suites"]["challenges_v26"]["baseline"]["case_count"], 6)
        self.assertEqual(report["suites"]["cohort"]["baseline"]["case_count"], 26)
        self.assertEqual(
            set(report["gates"]),
            {
                "baseline_identical",
                "no_critical_regression",
                "no_case_regression",
                "no_new_forbidden",
                "abstention_not_regressed",
                "ambiguity_never_contributes",
                "channels_visible",
                "bounded",
            },
        )
        self.assertTrue(all(type(value) is bool for value in report["gates"].values()))
        self.assertIs(report["promotion_authorized"], False)
        self.assertIs(report["retrieval_influence"], False)
        self.assertEqual(report["authority"], "evidence_only")
        self.assertIs(report["authorizes_actions"], False)
        json.dumps(report, sort_keys=True, allow_nan=False)

    def test_v26_shadow_equals_baseline(self) -> None:
        suite = self.first_report["suites"]["challenges_v26"]
        self.assertEqual(suite["baseline"], suite["shadow"])
        self.assertEqual(suite["identical_ranking_count"], suite["baseline"]["case_count"])
        self.assertEqual(suite["changed_ranking_count"], 0)
        self.assertTrue(all(not row["ontology_contributed"] for row in suite["cases"]))

    def test_corrupt_cohort_is_a_typed_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cohort = root / "palimnex/evaluation/ontology-shadow.v1.json"
            cohort.parent.mkdir(parents=True)
            cohort.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(OntologyEvaluationError) as raised:
                evaluate_ontology_shadow(root)
        self.assertEqual(raised.exception.reason, "invalid_fields")
        self.assertEqual(raised.exception.field, "cohort")

    def test_stale_binding_is_reported_instead_of_raising(self) -> None:
        cohort, _digest = _load_cohort_document(self.root)
        registry_document = copy.deepcopy(cohort["registry"])
        concept = registry_document["concepts"][0]
        concept["source_bindings"][0]["source_id"] = "docs/missing-ontology-source.md"
        registry, stale = _materialize_registry(registry_document, self.root)
        self.assertEqual(stale, (concept["concept_id"],))

        comparison = shadow_retrieve(
            "audit graph",
            registry=registry,
            root=self.root,
            snapshot=cache_v3.source_snapshot(self.root),
        )["comparison"]
        self.assertEqual(
            comparison["ontology_channel"]["excluded_stale"],
            [concept["concept_id"]],
        )
        self.assertEqual(comparison["ontology_channel"]["contributing_concept_ids"], [])

    def test_metrics_compute_recall_mrr_forbidden_and_critical_counts(self) -> None:
        first = _EvaluationCase(
            "positive", "control", "query", 5, ("a.md", "b.md"), ("x.md",), True
        )
        second = _EvaluationCase(
            "miss", "control", "query", 5, ("c.md",), (), False
        )
        outcomes = (
            self._case_outcome(
                first,
                _VariantOutcome(("x.md", "b.md"), 1, 2, 2, ("x.md",), False, False),
            ),
            self._case_outcome(
                second,
                _VariantOutcome(("z.md",), 0, 1, None, (), False, False),
            ),
        )
        metrics = _metric_summary(outcomes, "baseline")
        self.assertEqual(metrics["case_count"], 2)
        self.assertEqual(metrics["cases_passed"], 0)
        self.assertEqual(metrics["critical_pass_count"], 0)
        self.assertEqual(metrics["forbidden_path_hits"], 1)
        self.assertAlmostEqual(metrics["recall_at_limit"], 1 / 3)
        self.assertAlmostEqual(metrics["mrr"], 0.25)

    def test_metrics_handle_abstention_edges(self) -> None:
        positive = _EvaluationCase(
            "positive", "control", "query", 5, ("a.md",), (), False
        )
        no_negative = _metric_summary(
            (
                self._case_outcome(
                    positive,
                    _VariantOutcome(("a.md",), 1, 1, 1, (), True, False),
                ),
            ),
            "baseline",
        )
        self.assertEqual(no_negative["negative_case_count"], 0)
        self.assertEqual(no_negative["negative_abstention"], 1.0)

        negative_a = _EvaluationCase("negative-a", "negative", "query", 5, (), (), False)
        negative_b = _EvaluationCase("negative-b", "negative", "query", 5, (), (), False)
        with_negatives = _metric_summary(
            (
                self._case_outcome(
                    negative_a,
                    _VariantOutcome((), 0, 0, None, (), True, True),
                ),
                self._case_outcome(
                    negative_b,
                    _VariantOutcome(("a.md",), 0, 0, None, (), False, False),
                ),
            ),
            "baseline",
        )
        self.assertEqual(with_negatives["negative_case_count"], 2)
        self.assertEqual(with_negatives["negative_abstention"], 0.5)
        self.assertEqual(with_negatives["recall_at_limit"], 0.0)
        self.assertEqual(with_negatives["mrr"], 0.0)

    def test_critical_baseline_pass_shadow_fail_is_a_critical_regression(self) -> None:
        case = _EvaluationCase(
            "critical-regression", "control", "query", 5, ("a.md",), (), True
        )
        outcome = self._case_outcome(
            case,
            self._variant(("a.md",), passed=True),
            self._variant((), passed=False),
        )
        gates = _gates((outcome,))
        self.assertFalse(gates["no_critical_regression"])
        self.assertFalse(gates["no_case_regression"])
        self.assertEqual(_suite_report((outcome,))["regressed_case_ids"], [case.identifier])

    def test_noncritical_regression_fails_only_the_all_case_regression_gate(self) -> None:
        case = _EvaluationCase(
            "noncritical-regression", "control", "query", 5, ("a.md",), (), False
        )
        outcome = self._case_outcome(
            case,
            self._variant(("a.md",), passed=True),
            self._variant((), passed=False),
        )
        gates = _gates((outcome,))
        self.assertEqual(
            {
                name: gates[name]
                for name in (
                    "baseline_identical",
                    "no_critical_regression",
                    "no_case_regression",
                )
            },
            {
                "baseline_identical": True,
                "no_critical_regression": True,
                "no_case_regression": False,
            },
        )
        self.assertEqual(_suite_report((outcome,))["regressed_case_ids"], [case.identifier])

    def test_baseline_fail_shadow_pass_is_not_a_regression(self) -> None:
        case = _EvaluationCase(
            "improvement", "control", "query", 5, ("a.md",), (), True
        )
        outcome = self._case_outcome(
            case,
            self._variant(("z.md",), passed=False),
            self._variant(("a.md",), passed=True),
        )
        gates = _gates((outcome,))
        self.assertTrue(all(gates.values()))
        self.assertEqual(_suite_report((outcome,))["regressed_case_ids"], [])

    @mock.patch("palimnex.ontology_eval.retrieve_sources")
    @mock.patch("palimnex.ontology_eval.shadow_retrieve")
    def test_mismatching_direct_baseline_fails_identity_gate(
        self,
        shadow: mock.Mock,
        direct: mock.Mock,
    ) -> None:
        direct.return_value = {
            "results": [{"path": "a.md"}],
            "candidate_count": 1,
        }
        shadow.return_value = {
            "baseline": {
                "results": [{"path": "a.md"}],
                "candidate_count": 2,
            },
            "comparison": {
                "channels": ["lexical", "symbol", "graph", "ontology"],
                "ontology_channel": {
                    "contributing_concept_ids": [],
                    "excluded_stale": [],
                    "candidate_count": 0,
                    "truncated": False,
                },
                "limit": 5,
                "byte_budget": 8192,
                "shadow": {
                    "items": [
                        {
                            "pointer": "a.md:1-1",
                            "channels": {"lexical": 1},
                        }
                    ],
                    "candidate_count": 1,
                    "items_bytes": 1,
                },
                "diff": {"identical": True},
            },
        }
        case = _EvaluationCase(
            "baseline-mismatch", "control", "query", 5, ("a.md",), (), False
        )
        root = Path("synthetic-root")
        snapshot = object()
        outcome = _run_case(
            case,
            root=root,
            registry=None,
            report_limit=5,
            snapshot=snapshot,
        )
        self.assertFalse(_gates((outcome,))["baseline_identical"])
        direct.assert_called_once_with(
            "query",
            root=root,
            limit=5,
            byte_budget=8192,
            include_graph=True,
            client=None,
            snapshot=snapshot,
            influence="off",
        )

    def test_enabled_checkout_setting_cannot_influence_evaluation_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            config_path = root / ".palimnex.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["ontology_influence"] = {
                "mode": "enabled",
                "registry_digest": "a" * 64,
                "promotion_evidence": "missing-evidence.json",
                "promotion_evidence_digest": "b" * 64,
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            snapshot = cache_v3.source_snapshot(root)
            case = _EvaluationCase(
                "enabled-config",
                "control",
                "cobalt orchard recovery",
                5,
                ("docs/alpha.md",),
                (),
                False,
            )
            outcome = _run_case(
                case,
                root=root,
                registry=None,
                report_limit=5,
                snapshot=snapshot,
            )
            self.assertTrue(outcome.baseline_identical)

    def test_unchanged_gates_fail_on_their_defining_conditions(self) -> None:
        case = _EvaluationCase(
            "gate-condition", "control", "query", 5, ("a.md",), (), False
        )
        passing = self._variant(("a.md",), passed=True)
        outcome = self._case_outcome(case, passing)
        extra_forbidden = replace(
            outcome,
            shadow=_VariantOutcome(
                ("a.md", "x.md"), 1, 1, 1, ("x.md",), False, False
            ),
        )
        lost_abstention = replace(
            outcome,
            baseline=_VariantOutcome((), 0, 0, None, (), True, True),
            shadow=_VariantOutcome(("a.md",), 0, 0, None, (), False, False),
        )
        ambiguity_contributed = replace(
            outcome,
            case=replace(case, category="ambiguity"),
            ontology_contributed=True,
        )
        hidden_channels = replace(outcome, channels_visible=False)
        unbounded = replace(outcome, bounded=False)
        conditions = {
            "no_new_forbidden": extra_forbidden,
            "abstention_not_regressed": lost_abstention,
            "ambiguity_never_contributes": ambiguity_contributed,
            "channels_visible": hidden_channels,
            "bounded": unbounded,
        }
        for gate, condition in conditions.items():
            with self.subTest(gate=gate):
                self.assertFalse(_gates((condition,))[gate])

    @staticmethod
    def _variant(paths: tuple[str, ...], *, passed: bool) -> _VariantOutcome:
        return _VariantOutcome(
            paths,
            int(passed),
            1,
            1 if passed else None,
            (),
            passed,
            not paths,
        )

    @staticmethod
    def _case_outcome(
        case: _EvaluationCase,
        baseline: _VariantOutcome,
        shadow: _VariantOutcome | None = None,
    ) -> _CaseOutcome:
        return _CaseOutcome(
            case,
            baseline,
            baseline if shadow is None else shadow,
            False,
            True,
            True,
            True,
            True,
            (),
        )


if __name__ == "__main__":
    unittest.main()
