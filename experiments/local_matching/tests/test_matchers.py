import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from experiments.local_matching.data import load_matching_inputs
from experiments.local_matching.lexical import LexicalMatcher
from experiments.local_matching.semantic import SemanticMatcher


class FakeEncoder:
    TERMS = ("python", "kubernetes", "accounting")

    def encode(self, sentences, **_kwargs):
        return [[float(term in sentence.lower()) for term in self.TERMS] for sentence in sentences]


class LocalMatcherTests(unittest.TestCase):
    def test_loader_uses_cleaned_text_and_original_resume_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.db"
            with sqlite3.connect(database) as db:
                db.executescript("""
                    CREATE TABLE jobs (job_uid TEXT, page_title TEXT, application_status TEXT);
                    CREATE TABLE job_artifacts (
                        job_uid TEXT, cleaned_json TEXT, structured_json TEXT, ranked_json TEXT
                    );
                    CREATE TABLE profiles (
                        profile_name TEXT, resume_text TEXT, profile_json TEXT, enabled INTEGER
                    );
                """)
                db.execute("INSERT INTO jobs VALUES ('j1', 'Python role', 'new')")
                db.execute("INSERT INTO jobs VALUES ('j2', 'Experiment role', 'experiment')")
                db.execute(
                    "INSERT INTO job_artifacts VALUES (?, ?, ?, ?)",
                    ("j1", json.dumps({"description_text": "clean Python text"}),
                     json.dumps({"description": "AI SECRET"}), json.dumps({"score": 99})),
                )
                db.execute(
                    "INSERT INTO profiles VALUES (?, ?, ?, 1)",
                    ("backend", "original resume", json.dumps({"summary": "AI PROFILE"})),
                )
                db.execute(
                    "INSERT INTO job_artifacts VALUES (?, ?, ?, ?)",
                    ("j2", json.dumps({"description_text": "experiment text"}), None, None),
                )
                db.execute(
                    "INSERT INTO profiles VALUES (?, ?, ?, 1)",
                    ("other", "other original resume", "{}"),
                )

            jobs, profiles = load_matching_inputs(
                database, status="new", profile_name="backend"
            )
            self.assertEqual(1, len(jobs))
            self.assertEqual(1, len(profiles))
            self.assertEqual("clean Python text", jobs[0].text)
            self.assertEqual("original resume", profiles[0].text)
            self.assertNotIn("AI", jobs[0].text + profiles[0].text)

    def test_lexical_match_rewards_shared_technical_terms(self) -> None:
        from experiments.local_matching.data import JobInput, ProfileInput
        jobs = [JobInput("j", "", "Python Kubernetes engineer", "new")]
        profiles = [
            ProfileInput("matching", "Python Kubernetes developer"),
            ProfileInput("other", "Financial accounting specialist"),
        ]
        matcher = LexicalMatcher(jobs, profiles)
        self.assertGreater(
            matcher.compare(jobs[0].text, profiles[0].text).score,
            matcher.compare(jobs[0].text, profiles[1].text).score,
        )

    def test_semantic_matcher_chunks_and_rewards_related_vectors(self) -> None:
        matcher = SemanticMatcher(FakeEncoder(), max_words=3)
        related = matcher.compare("Python APIs and Kubernetes services", "Python Kubernetes developer")
        unrelated = matcher.compare("Python APIs and Kubernetes services", "Accounting and finance")
        self.assertGreater(related, unrelated)


if __name__ == "__main__":
    unittest.main()
