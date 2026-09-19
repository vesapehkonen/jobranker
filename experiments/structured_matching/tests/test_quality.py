from __future__ import annotations

import unittest

from experiments.structured_matching.quality import (
    technology_confidence,
    validate_job_text,
)


class JobTextQualityTests(unittest.TestCase):
    def test_navigation_placeholder_is_invalid(self) -> None:
        result = validate_job_text("0 notifications\nNavigating to Jobs")
        self.assertEqual("invalid", result["status"])
        self.assertIn("too_short", result["reasons"])

    def test_short_careers_landing_page_is_invalid(self) -> None:
        result = validate_job_text(
            "Home | Company | Contact Sales | Careers | View open positions | "
            "Join our Talent Community"
        )
        self.assertEqual("invalid", result["status"])
        self.assertIn("navigation_only", result["reasons"])

    def test_short_recruiter_description_with_requirements_is_valid(self) -> None:
        result = validate_job_text(
            "We are looking for a DevOps engineer. You will automate infrastructure. "
            "Requirements: 5 years of experience with cloud systems."
        )
        self.assertEqual("valid", result["status"])

    def test_long_news_page_without_job_content_is_invalid(self):
        text = "Latest news. Sports results, weather forecasts and city council updates. " * 240
        result = validate_job_text(text)
        self.assertGreater(result["character_count"], 15000)
        self.assertEqual(0, result["content_signal_count"])
        self.assertEqual("invalid", result["status"])
        self.assertIn("missing_job_content", result["reasons"])

    def test_technology_confidence_uses_evidence_count(self) -> None:
        self.assertEqual("unknown", technology_confidence(0))
        self.assertEqual("low", technology_confidence(1))
        self.assertEqual("low", technology_confidence(2))
        self.assertEqual("high", technology_confidence(3))


if __name__ == "__main__":
    unittest.main()
