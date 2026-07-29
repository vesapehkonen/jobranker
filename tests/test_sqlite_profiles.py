import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from database import (
    connect,
    initialize_database,
    list_profiles,
    load_enabled_profiles,
    save_profile,
)
from extract_resume_ai import extract_resume


class FakeResponses:
    def __init__(self, profile: dict):
        self.profile = profile
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(output_text=json.dumps(self.profile))


class SQLiteProfileTests(unittest.TestCase):
    def test_profile_upsert_and_enabled_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            initialize_database(database_file)
            first = save_profile(
                "backend", "resume v1", {"candidate_title": "Engineer"},
                database_file=database_file,
            )
            second = save_profile(
                "backend", "resume v2", {"candidate_title": "Senior Engineer"},
                database_file=database_file,
            )
            self.assertNotEqual(first["profile_hash"], second["profile_hash"])
            self.assertEqual(
                {"backend": {"candidate_title": "Senior Engineer"}},
                load_enabled_profiles(database_file=database_file),
            )
            self.assertEqual(1, len(list_profiles(database_file=database_file)))
            with connect(database_file) as db:
                row = db.execute(
                    "SELECT resume_text FROM profiles WHERE profile_name = 'backend'"
                ).fetchone()
            self.assertEqual("resume v2", row["resume_text"])

    def test_disabled_profile_is_not_loaded_or_reenabled_by_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            initialize_database(database_file)
            save_profile("backend", "resume", {"title": "Engineer"}, database_file=database_file)
            save_profile("cloud", "resume", {"title": "Cloud Engineer"}, database_file=database_file)
            with connect(database_file) as db:
                db.execute("UPDATE profiles SET enabled = 0 WHERE profile_name = 'cloud'")
            save_profile("cloud", "new resume", {"title": "Senior Cloud Engineer"}, database_file=database_file)
            self.assertEqual(
                {"backend": {"title": "Engineer"}},
                load_enabled_profiles(database_file=database_file),
            )

    def test_resume_extraction_accepts_text_and_returns_dictionary(self) -> None:
        expected = {"candidate_title": "Backend Engineer"}
        responses = FakeResponses(expected)
        client = SimpleNamespace(responses=responses)
        profile = extract_resume(client, "resume contents")
        self.assertEqual(expected, profile)
        self.assertEqual("resume contents", responses.request["input"][1]["content"])


if __name__ == "__main__":
    unittest.main()
