from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from jsonschema import Draft202012Validator

from palimnex import core, ontology_eval, semantic_eval
from palimnex.durable import canonical_json
from palimnex.semantic_local import PROVIDER_DIMENSIONS, identity_digest, provider_identity
from palimnex.semantic_shadow import EmbeddingMemo


class _Provider:
    model_id = "semantic-eval-test-provider"
    revision = "1"
    dimensions = PROVIDER_DIMENSIONS
    artifact_digest = hashlib.sha256(model_id.encode("utf-8")).hexdigest()

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(core.embedding(text, self.dimensions) for text in texts)


class _ChangingProvider(_Provider):
    def __init__(self) -> None:
        self.reads = 0

    @property
    def artifact_digest(self) -> str:
        self.reads += 1
        return hashlib.sha256(f"identity-{self.reads}".encode("utf-8")).hexdigest()


class _TickClock:
    def __init__(self, step: int = 1_000_000) -> None:
        self.value = 0
        self.step = step

    def __call__(self) -> int:
        self.value += self.step
        return self.value


class _BrokenMemo(EmbeddingMemo):
    """Return the first stored vector for every later content digest."""

    def __init__(self) -> None:
        super().__init__()
        self.stale: tuple[float, ...] | None = None

    def _get(self, key: tuple[str, str]) -> tuple[float, ...] | None:
        del key
        return self.stale

    def _put(self, key: tuple[str, str], vector: tuple[float, ...]) -> None:
        del key
        if self.stale is None:
            self.stale = vector


def _case(
    identifier: str,
    *,
    category: str = "control",
    expected: tuple[str, ...] = ("target.py",),
    forbidden: tuple[str, ...] = (),
    critical: bool = False,
) -> ontology_eval._EvaluationCase:
    return ontology_eval._EvaluationCase(
        identifier,
        category,
        "where is the target behavior",
        5,
        expected,
        forbidden,
        critical,
    )


def _outcome(
    case: ontology_eval._EvaluationCase,
    baseline_paths: tuple[str, ...],
    shadow_paths: tuple[str, ...],
    provider_digest: str,
    *,
    comparison_digest: str = "a" * 64,
    candidate_count: int = 1,
    suppressed: str | None = None,
    baseline_identical: bool = True,
    channels_visible: bool = True,
    bounded: bool = True,
) -> semantic_eval._RunOutcome:
    baseline = ontology_eval._variant_outcome(
        baseline_paths, case.expected_paths, case.forbidden_paths
    )
    shadow = ontology_eval._variant_outcome(
        shadow_paths, case.expected_paths, case.forbidden_paths
    )
    value = ontology_eval._CaseOutcome(
        case,
        baseline,
        shadow,
        candidate_count > 0,
        baseline_paths == shadow_paths,
        baseline_identical,
        channels_visible,
        bounded,
        (),
    )
    return semantic_eval._RunOutcome(
        value,
        candidate_count,
        suppressed,
        comparison_digest,
        provider_digest,
        {},
    )


class SemanticEvaluationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.provider = _Provider()
        self.provider_digest = identity_digest(provider_identity(self.provider))

    def _sets(self) -> dict[str, tuple[semantic_eval._RunOutcome, ...]]:
        protected = _outcome(
            _case("protected", critical=True),
            ("target.py",),
            ("target.py",),
            self.provider_digest,
        )
        semantic = _outcome(
            _case("semantic-gain", category="paraphrase"),
            ("other.py",),
            ("target.py",),
            self.provider_digest,
        )
        drift = _outcome(
            _case("drift", category="drift"),
            ("target.py",),
            ("target.py",),
            self.provider_digest,
        )
        privacy = semantic_eval._privacy_outcome(
            _case("privacy", category="privacy_canary", expected=())
        )
        return {
            "v27": (protected,),
            "challenges_v26": (protected,),
            "ontology_cohort": (protected,),
            "semantic_cohort": (semantic,),
            "semantic_repeat": (copy.deepcopy(semantic),),
            "drift": (drift,),
            "privacy": (privacy,),
        }

    def _evaluate(
        self,
        *,
        sets: dict[str, tuple[semantic_eval._RunOutcome, ...]] | None = None,
        provider: object | None = None,
        benchmark: bool = True,
        benchmark_report: dict[str, Any] | None = None,
        source_drift: bool = True,
        privacy_canary: bool = True,
        privacy_canaries: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        active_sets = self._sets() if sets is None else sets
        semantic_case = active_sets["semantic_cohort"][0].outcome.case
        loaded = [
            active_sets["v27"],
            active_sets["challenges_v26"],
            active_sets["ontology_cohort"],
            active_sets["semantic_cohort"],
            active_sets["semantic_repeat"],
        ]
        timing = benchmark_report or {
            "run": True,
            "baseline_p95_ms": 10.0,
            "semantic_p95_ms": 12.0,
            "multiplier_limit": 1.5,
            "samples_per_variant": 3,
        }
        snapshot = SimpleNamespace(fingerprint="stable")
        cohort = {
            "schema": "palimnex:semantic-shadow-cohort:v1",
            "status": "frozen",
            "description": "test",
            "cases": [],
            "projects": {},
            "project_cases": [],
        }
        with (
            patch.object(semantic_eval, "_load_semantic_cohort", return_value=(cohort, "f" * 64)),
            patch.object(semantic_eval, "_repository_cases", return_value=(semantic_case,)),
            patch.object(semantic_eval.cache_v3, "source_snapshot", return_value=snapshot),
            patch.object(semantic_eval.ontology_eval, "_load_v27_cases", return_value=(semantic_case,)),
            patch.object(
                semantic_eval.ontology_eval,
                "_load_cohort_document",
                return_value=({"cases": []}, "e" * 64),
            ),
            patch.object(semantic_eval.ontology_eval, "_cohort_cases", return_value=(semantic_case,)),
            patch.object(semantic_eval.ontology_eval, "_load_v26", return_value=({}, (semantic_case,))),
            patch.object(semantic_eval, "_run_suite", side_effect=loaded),
            patch.object(
                semantic_eval,
                "_run_drift",
                return_value=(active_sets["drift"], source_drift),
            ),
            patch.object(
                semantic_eval,
                "_run_privacy",
                return_value=(
                    active_sets["privacy"],
                    privacy_canary,
                    privacy_canaries,
                ),
            ),
            patch.object(semantic_eval, "_benchmark", return_value=timing),
        ):
            return semantic_eval.evaluate_semantic_shadow(
                Path("/synthetic"),
                provider=self.provider if provider is None else provider,
                benchmark=benchmark,
            )

    def test_promotable_report_validates_and_is_non_authorizing(self) -> None:
        report = self._evaluate()
        schema = json.loads(
            Path("palimnex/schemas/semantic-shadow-evaluation.v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(schema).validate(report)
        self.assertEqual(report["status"], "promotable")
        self.assertTrue(all(report["gates"].values()))
        self.assertFalse(report["promotion_authorized"])
        self.assertFalse(report["retrieval_influence"])
        self.assertFalse(report["authorizes_actions"])

    def test_report_is_deterministic_outside_timing_values(self) -> None:
        first = self._evaluate()
        second = self._evaluate(
            benchmark_report={
                "run": True,
                "baseline_p95_ms": 11.0,
                "semantic_p95_ms": 13.0,
                "multiplier_limit": 1.5,
                "samples_per_variant": 3,
            }
        )
        first.pop("benchmark")
        second.pop("benchmark")
        self.assertEqual(first, second)

    def test_benchmark_false_holds_report(self) -> None:
        report = self._evaluate(benchmark=False)
        self.assertEqual(report["status"], "held")
        self.assertFalse(report["gates"]["latency_within_bound"])
        self.assertIn("benchmark_not_run", report["held_reasons"])
        self.assertFalse(report["benchmark"]["run"])

    def test_regression_forbidden_abstention_and_ambiguity_gates_fail(self) -> None:
        scenarios: list[tuple[str, dict[str, tuple[semantic_eval._RunOutcome, ...]], str]] = []

        regression = self._sets()
        critical = _case("critical-regression", critical=True)
        regression["v27"] = (
            _outcome(critical, ("target.py",), ("other.py",), self.provider_digest),
        )
        scenarios.append(("critical", regression, "no_critical_regression"))

        forbidden = self._sets()
        forbidden_case = _case("forbidden", forbidden=("bad.py",))
        forbidden["drift"] = (
            _outcome(
                forbidden_case,
                ("target.py",),
                ("target.py", "bad.py"),
                self.provider_digest,
            ),
        )
        scenarios.append(("forbidden", forbidden, "no_new_forbidden"))

        abstention = self._sets()
        negative = _case("negative", category="negative", expected=())
        abstention["drift"] = (
            _outcome(negative, (), ("other.py",), self.provider_digest),
        )
        scenarios.append(("abstention", abstention, "abstention_not_regressed"))

        ambiguity = self._sets()
        ambiguous = _case(
            "ambiguous",
            category="ambiguity",
            expected=("one.py", "two.py"),
        )
        ambiguity["drift"] = (
            _outcome(
                ambiguous,
                ("one.py", "two.py"),
                ("one.py",),
                self.provider_digest,
            ),
        )
        scenarios.append(("ambiguity", ambiguity, "ambiguity_not_collapsed"))

        for name, values, gate in scenarios:
            with self.subTest(name=name):
                self.assertFalse(self._evaluate(sets=values)["gates"][gate])

    def test_remaining_quality_and_contract_gates_can_fail(self) -> None:
        scenarios: list[tuple[str, dict[str, tuple[semantic_eval._RunOutcome, ...]], str]] = []

        baseline_identity = self._sets()
        item = baseline_identity["drift"][0]
        baseline_identity["drift"] = (
            _outcome(
                item.outcome.case,
                item.outcome.baseline.paths,
                item.outcome.shadow.paths,
                self.provider_digest,
                baseline_identical=False,
            ),
        )
        scenarios.append(("baseline", baseline_identity, "baseline_identical"))

        protected_recall = self._sets()
        protected = _case("protected-recall")
        protected_recall["v27"] = (
            _outcome(
                protected,
                ("target.py",),
                ("other.py",),
                self.provider_digest,
            ),
        )
        scenarios.append(
            ("protected-recall", protected_recall, "protected_recall_not_reduced")
        )

        no_gain = self._sets()
        semantic_case = _case("no-gain", category="paraphrase")
        unchanged = _outcome(
            semantic_case,
            ("target.py",),
            ("target.py",),
            self.provider_digest,
        )
        no_gain["semantic_cohort"] = (unchanged,)
        no_gain["semantic_repeat"] = (copy.deepcopy(unchanged),)
        scenarios.append(("gain", no_gain, "cohort_gain"))
        scenarios.append(("additional", no_gain, "cohort_additional_pass"))

        hidden = self._sets()
        item = hidden["drift"][0]
        hidden["drift"] = (
            _outcome(
                item.outcome.case,
                item.outcome.baseline.paths,
                item.outcome.shadow.paths,
                self.provider_digest,
                channels_visible=False,
            ),
        )
        scenarios.append(("channels", hidden, "channels_visible"))

        unbounded = self._sets()
        item = unbounded["drift"][0]
        unbounded["drift"] = (
            _outcome(
                item.outcome.case,
                item.outcome.baseline.paths,
                item.outcome.shadow.paths,
                self.provider_digest,
                bounded=False,
            ),
        )
        scenarios.append(("bounded", unbounded, "bounded"))

        for name, values, gate in scenarios:
            with self.subTest(name=name):
                self.assertFalse(self._evaluate(sets=values)["gates"][gate])

    def test_nondeterministic_comparison_is_held(self) -> None:
        values = self._sets()
        original = values["semantic_repeat"][0]
        values["semantic_repeat"] = (
            semantic_eval._RunOutcome(
                original.outcome,
                original.semantic_candidate_count,
                original.suppressed,
                "b" * 64,
                original.provider_identity_digest,
                original.comparison,
            ),
        )
        report = self._evaluate(sets=values)
        self.assertFalse(report["gates"]["deterministic"])
        self.assertIn("deterministic", report["held_reasons"])

    def test_identity_change_mid_run_is_held(self) -> None:
        report = self._evaluate(provider=_ChangingProvider())
        self.assertFalse(report["gates"]["provider_identity_bound"])

    def test_protected_recall_uses_exact_comparison(self) -> None:
        original = semantic_eval._suite_report

        def suite_report(
            outcomes: tuple[semantic_eval._RunOutcome, ...],
            *,
            shadow_recall: float,
        ) -> dict[str, Any]:
            report = original(outcomes)
            report["baseline"]["recall_at_limit"] = 0.5
            report["shadow"]["recall_at_limit"] = shadow_recall
            return report

        with patch.object(
            semantic_eval,
            "_suite_report",
            side_effect=lambda outcomes: suite_report(outcomes, shadow_recall=0.5),
        ):
            equal = self._evaluate()
        with patch.object(
            semantic_eval,
            "_suite_report",
            side_effect=lambda outcomes: suite_report(
                outcomes, shadow_recall=0.5 - 1e-13
            ),
        ):
            worse = self._evaluate()
        self.assertTrue(equal["gates"]["protected_recall_not_reduced"])
        self.assertFalse(worse["gates"]["protected_recall_not_reduced"])

    def test_negative_abstention_uses_exact_comparison(self) -> None:
        original = semantic_eval._suite_report

        def suite_report(
            outcomes: tuple[semantic_eval._RunOutcome, ...],
            *,
            shadow_abstention: float,
        ) -> dict[str, Any]:
            report = original(outcomes)
            report["baseline"]["negative_abstention"] = 0.5
            report["shadow"]["negative_abstention"] = shadow_abstention
            return report

        with patch.object(
            semantic_eval,
            "_suite_report",
            side_effect=lambda outcomes: suite_report(outcomes, shadow_abstention=0.5),
        ):
            equal = self._evaluate()
        with patch.object(
            semantic_eval,
            "_suite_report",
            side_effect=lambda outcomes: suite_report(
                outcomes, shadow_abstention=0.5 - 1e-13
            ),
        ):
            worse = self._evaluate()
        self.assertTrue(equal["gates"]["abstention_not_regressed"])
        self.assertFalse(worse["gates"]["abstention_not_regressed"])

    def test_latency_multiplier_uses_exact_comparison(self) -> None:
        equal = self._evaluate(
            benchmark_report={
                "run": True,
                "baseline_p95_ms": 10.0,
                "semantic_p95_ms": 15.0,
                "multiplier_limit": 1.5,
                "samples_per_variant": 3,
            }
        )
        worse = self._evaluate(
            benchmark_report={
                "run": True,
                "baseline_p95_ms": 10.0,
                "semantic_p95_ms": 15.0 + 1e-13,
                "multiplier_limit": 1.5,
                "samples_per_variant": 3,
            }
        )
        self.assertTrue(equal["gates"]["latency_within_bound"])
        self.assertFalse(worse["gates"]["latency_within_bound"])

    def test_source_drift_and_privacy_gate_results_are_binding(self) -> None:
        drift = self._evaluate(source_drift=False)
        privacy = self._evaluate(privacy_canary=False)
        self.assertFalse(drift["gates"]["source_drift"])
        self.assertFalse(privacy["gates"]["privacy_canary"])

    def test_report_canary_leak_is_redacted_and_held(self) -> None:
        canary = semantic_eval._canary("aws-access-key")
        original = semantic_eval._suite_report

        def leaking_suite_report(
            outcomes: tuple[semantic_eval._RunOutcome, ...],
        ) -> dict[str, Any]:
            report = original(outcomes)
            report["cases"][0]["id"] = canary
            return report

        with patch.object(
            semantic_eval, "_suite_report", side_effect=leaking_suite_report
        ):
            report = self._evaluate(privacy_canaries=(canary,))
        self.assertFalse(report["gates"]["privacy_canary"])
        self.assertEqual(report["status"], "held")
        self.assertIn("privacy_canary", report["held_reasons"])
        self.assertNotIn(canary, canonical_json(report).decode("utf-8"))

    def test_r15_benchmark_uses_three_samples_per_query(self) -> None:
        case = _case("benchmark")
        clock = _TickClock()
        with (
            patch.object(semantic_eval.retrieval, "retrieve_sources", return_value={}),
            patch.object(semantic_eval, "semantic_shadow_retrieve", return_value={}),
        ):
            report = semantic_eval._benchmark(
                (case,),
                provider=self.provider,
                root=Path("/synthetic"),
                snapshot=SimpleNamespace(),
                clock_ns=clock,
            )
        self.assertEqual(report["samples_per_variant"], 3)
        self.assertEqual(report["baseline_p95_ms"], 1.0)
        self.assertEqual(report["semantic_p95_ms"], 1.0)

    def test_modified_cohort_is_refused_by_pinned_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = Path("fixture.json")
            (root / relative).write_text("{}\n", encoding="utf-8")
            with (
                patch.object(semantic_eval, "COHORT_PATH", relative),
                patch.object(semantic_eval, "COHORT_SHA256", "0" * 64),
            ):
                with self.assertRaises(semantic_eval.SemanticEvaluationError) as raised:
                    semantic_eval._load_semantic_cohort(root)
        self.assertEqual(raised.exception.reason, "fixture_digest_mismatch")
        self.assertNotIn("{}", str(raised.exception))

    def test_real_memo_passes_source_drift(self) -> None:
        document = self._drift_document()
        outcomes, passed = semantic_eval._run_drift(document, self.provider)
        self.assertEqual(len(outcomes), 1)
        self.assertTrue(passed)

    def test_broken_memo_fails_source_drift(self) -> None:
        document = self._drift_document(changed_text=True)
        with patch.object(
            semantic_eval,
            "EmbeddingMemo",
            side_effect=[_BrokenMemo(), EmbeddingMemo()],
        ):
            _outcomes, passed = semantic_eval._run_drift(document, self.provider)
        self.assertFalse(passed)

    def _drift_document(self, *, changed_text: bool = False) -> dict[str, Any]:
        before = (
            "Stalled jobs are archived permanently and never attempted again."
            if changed_text
            else "Stalled jobs are attempted again after a short waiting period."
        )
        return {
            "projects": {
                "move": {
                    "documents": {
                        "README.md": "A sample delayed-work service.",
                        "src/old.py": before,
                    },
                    "after": {
                        "src/old.py": None,
                        "src/new.py": "Stalled jobs are attempted again after a short waiting period.",
                    },
                }
            },
            "project_cases": [
                {
                    "id": "drift-move",
                    "category": "drift",
                    "project": "move",
                    "query": "How are stalled jobs attempted again after waiting?",
                    "expected_paths": ["src/new.py"],
                    "forbidden_paths": ["src/old.py"],
                }
            ],
        }

    def test_privacy_canaries_are_refused_without_echo_or_provider_input(self) -> None:
        document = {
            "projects": {
                "query": {
                    "documents": {
                        "README.md": "Session state remains local.",
                        "src/session.py": "Session state uses a bounded local record.",
                    },
                    "after": {},
                },
                "corpus": {
                    "documents": {
                        "README.md": "A local provider sample.",
                        "config/provider.txt": "The provider value is {canary}.",
                    },
                    "after": {},
                },
            },
            "project_cases": [
                {
                    "id": "query-canary",
                    "category": "privacy_canary",
                    "project": "query",
                    "query": "{canary} where is session state stored",
                    "expected_paths": [],
                    "forbidden_paths": [],
                    "canary_kind": "query",
                    "canary_rule": "aws-access-key",
                },
                {
                    "id": "corpus-canary",
                    "category": "privacy_canary",
                    "project": "corpus",
                    "query": "how is the provider configured",
                    "expected_paths": [],
                    "forbidden_paths": ["config/provider.txt"],
                    "canary_kind": "corpus",
                    "canary_rule": "openai-token",
                },
            ],
        }
        outcomes, passed, canaries = semantic_eval._run_privacy(document, self.provider)
        self.assertTrue(passed)
        serialized = canonical_json(semantic_eval._suite_report(outcomes)).decode("utf-8")
        for canary in canaries:
            self.assertNotIn(canary, serialized)


if __name__ == "__main__":
    unittest.main()
