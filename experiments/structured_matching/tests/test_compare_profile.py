from __future__ import annotations

import unittest

from experiments.structured_matching.compare_profile import compare


class ProfileComparisonTests(unittest.TestCase):
    def test_compares_technology_experience_and_education(self) -> None:
        job = {
            "technologies": [
                {"name": name}
                for name in ("Python", "AWS", "Terraform", "Kubernetes", "Java", "Spark")
            ],
            "capabilities": [
                {"name": name}
                for name in ("CI/CD", "Microservices", "Observability")
            ],
            "experience": {"minimum_years": 5},
            "education": {"minimum_level": "bachelor"},
        }
        profile = {
            "technologies": [
                "Python", "AWS", "Terraform", "Kubernetes", "Docker", "Linux"
            ],
            "capabilities": ["CI/CD", "Microservices", "Test Automation"],
            "experience": {"total_years": 8.0},
            "education": {"highest_level": "bachelor"},
        }

        result = compare(job, profile)

        self.assertEqual(6, result["technology"]["job_count"])
        self.assertEqual(4, result["technology"]["matched_count"])
        self.assertEqual(0.667, result["technology"]["coverage"])
        self.assertEqual(["Java", "Spark"], result["technology"]["job_only"])
        self.assertEqual(2, result["capability"]["matched_count"])
        self.assertEqual(0.667, result["capability"]["coverage"])
        self.assertEqual(["Observability"], result["capability"]["job_only"])
        self.assertEqual(3.0, result["experience"]["difference"])
        self.assertEqual(1.6, result["experience"]["ratio"])
        self.assertTrue(result["experience"]["meets"])
        self.assertTrue(result["education"]["meets"])

    def test_no_job_requirements_are_treated_as_met(self) -> None:
        result = compare(
            {
                "technologies": [],
                "capabilities": [],
                "experience": {"minimum_years": None},
                "education": {"minimum_level": None},
            },
            {
                "technologies": ["Python"],
                "capabilities": ["CI/CD"],
                "experience": {"total_years": 2.0},
                "education": {"highest_level": "associate"},
            },
        )

        self.assertIsNone(result["technology"]["coverage"])
        self.assertEqual("unknown", result["technology"]["confidence"])
        self.assertIsNone(result["capability"]["coverage"])
        self.assertIsNone(result["experience"]["difference"])
        self.assertIsNone(result["experience"]["ratio"])
        self.assertTrue(result["experience"]["meets"])
        self.assertTrue(result["education"]["meets"])

    def test_invalid_job_skips_all_comparisons(self) -> None:
        result = compare(
            {
                "input_quality": {"status": "invalid", "reasons": ["navigation_only"]},
                "technologies": [],
                "experience": None,
                "education": None,
            },
            {
                "technologies": ["Python"],
                "experience": {"total_years": 8},
                "education": {"highest_level": "bachelor"},
            },
        )
        self.assertEqual("invalid_job_description", result["comparison_status"])
        self.assertIsNone(result["technology"])
        self.assertIsNone(result["capability"])
        self.assertIsNone(result["experience"])
        self.assertIsNone(result["education"])

    def test_higher_education_meets_lower_requirement(self) -> None:
        result = compare(
            {
                "technologies": [],
                "experience": {"minimum_years": 3},
                "education": {"minimum_level": "associate"},
            },
            {
                "technologies": [],
                "experience": {"total_years": 2},
                "education": {"highest_level": "bachelor"},
            },
        )

        self.assertFalse(result["experience"]["meets"])
        self.assertTrue(result["education"]["meets"])


if __name__ == "__main__":
    unittest.main()
