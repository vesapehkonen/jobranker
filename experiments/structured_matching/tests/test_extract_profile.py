from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from experiments.structured_matching.extract_profile import (
    build_local_profile,
    extract_experience,
    load_resume,
)


class LocalProfileExtractionTests(unittest.TestCase):
    def test_builds_canonical_local_profile(self) -> None:
        resume = """Backend engineer using Python, AWS, Postgres, and K8s.
Designs distributed systems and microservices with CI/CD and automated testing.

EXPERIENCE
Engineer 3/2020 - 6/2021
Senior Engineer 6/2021 - Present

EDUCATION
Bachelor of Science in Computer Engineering
"""
        profile = build_local_profile("backend", resume, as_of=(2022, 3))

        self.assertEqual(
            ["AWS", "Kubernetes", "PostgreSQL", "Python"],
            profile["technologies"],
        )
        self.assertEqual("bachelor", profile["education"]["highest_level"])
        self.assertEqual(
            ["CI/CD", "Distributed Systems", "Microservices", "Test Automation"],
            profile["capabilities"],
        )
        self.assertEqual(25, profile["experience"]["total_months"])

    def test_experience_merges_overlapping_periods(self) -> None:
        result = extract_experience(
            """EXPERIENCE
Role A Jan 2020 – Dec 2020
Role B 6/2020 – 6/2021

PROJECTS
Project 2010 - 2018
""",
            as_of=(2022, 1),
        )
        self.assertEqual(18, result["total_months"])
        self.assertEqual(
            [{"start": "2020-01", "end": "2021-06"}],
            result["merged_periods"],
        )

    def test_load_resume_reads_only_requested_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "profiles.db"
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE profiles (profile_name TEXT, resume_text TEXT)")
                db.execute("INSERT INTO profiles VALUES ('backend', 'Python resume')")
                db.execute("INSERT INTO profiles VALUES ('cloud', 'AWS resume')")

            self.assertEqual("Python resume", load_resume(database, "backend"))


if __name__ == "__main__":
    unittest.main()
