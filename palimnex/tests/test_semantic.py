from __future__ import annotations

import unittest

from palimnex.semantic import SemanticMetrics, promotion_decision, semantic_status


class SemanticBoundaryTests(unittest.TestCase):
    def test_portable_configuration_is_disabled_and_network_free(self) -> None:
        status = semantic_status({"semantic_provider": {"mode": "disabled"}})
        self.assertEqual(status["mode"], "disabled")
        self.assertFalse(status["external_network_enabled"])
        self.assertFalse(status["provider_registered"])
        self.assertFalse(status["retrieval_influence"])
        with self.assertRaisesRegex(ValueError, "no semantic runtime"):
            semantic_status({"semantic_provider": {"mode": "remote"}})

    def test_promotion_requires_value_no_critical_regression_and_latency_bound(self) -> None:
        baseline = SemanticMetrics(0.80, 0.75, True, 10.0)
        promotable = promotion_decision(
            baseline, SemanticMetrics(0.85, 0.76, True, 20.0)
        )
        self.assertTrue(promotable["promotable"])
        self.assertEqual(promotable["status"], "promotable")

        cases = (
            SemanticMetrics(0.84, 0.79, True, 10.0),
            SemanticMetrics(0.86, 0.80, False, 10.0),
            SemanticMetrics(0.86, 0.80, True, 20.01),
            SemanticMetrics(0.79, 0.81, True, 10.0),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.assertFalse(promotion_decision(baseline, candidate)["promotable"])

    def test_invalid_metrics_fail_closed(self) -> None:
        baseline = SemanticMetrics(0.8, 0.7, True, 1.0)
        invalid_candidates = (
            SemanticMetrics(1.1, 0.8, True, 1.0),
            SemanticMetrics(float("nan"), 0.8, True, 1.0),
            SemanticMetrics(0.9, float("inf"), True, 1.0),
            SemanticMetrics(0.9, 0.8, True, float("-inf")),
            SemanticMetrics(0.9, 0.8, 1, 1.0),
        )
        for candidate in invalid_candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(ValueError, "outside"):
                    promotion_decision(baseline, candidate)
        with self.assertRaisesRegex(ValueError, "outside"):
            promotion_decision(
                SemanticMetrics(0.8, 0.7, "yes", 1.0),
                SemanticMetrics(0.9, 0.8, True, 1.0),
            )


if __name__ == "__main__":
    unittest.main()
