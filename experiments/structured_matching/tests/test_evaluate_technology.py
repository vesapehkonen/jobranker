from __future__ import annotations

import unittest

from experiments.structured_matching.evaluate_technology import evaluate, spearman


class TechnologyEvaluationTests(unittest.TestCase):
    def test_spearman_handles_order_and_ties(self) -> None:
        self.assertEqual(1.0, spearman([0.2, 0.5, 0.8], [50, 70, 90]))
        self.assertEqual(-1.0, spearman([0.2, 0.5, 0.8], [90, 70, 50]))
        self.assertIsNone(spearman([0.5], [70]))

    def test_evaluate_reports_simple_disagreement_count(self) -> None:
        comparisons = [
            ("good", {"technology": {
                "coverage": 0.8, "confidence": "high", "job_count": 5, "matched_count": 4,
            }, "capability": {
                "coverage": 0.75, "confidence": "high", "job_count": 4, "matched_count": 3,
            }}),
            ("disagreement", {"technology": {
                "coverage": 0.2, "confidence": "high", "job_count": 5, "matched_count": 1,
            }}),
            ("no-tech", {"technology": {
                "coverage": None, "confidence": "unknown", "job_count": 0, "matched_count": 0,
            }}),
            ("invalid", {
                "input_quality": {"status": "invalid", "reasons": ["too_short"]},
                "technology": None,
            }),
        ]
        rows, summary = evaluate(
            comparisons, {
                "good": 90, "disagreement": 75, "no-tech": 80, "invalid": 85,
            }
        )

        self.assertEqual(4, summary["job_count"])
        self.assertEqual(2, summary["comparable_job_count"])
        self.assertEqual(1, summary["invalid_job_count"])
        self.assertEqual({"unknown": 1, "low": 0, "high": 2}, summary["technology_confidence"])
        self.assertEqual(1, summary["low_coverage_high_ai_count"])
        self.assertEqual(1, summary["capability_comparable_job_count"])
        self.assertEqual({"unknown": 2, "low": 0, "high": 1}, summary["capability_confidence"])
        self.assertTrue(rows[1]["low_coverage_high_ai"])


if __name__ == "__main__":
    unittest.main()
