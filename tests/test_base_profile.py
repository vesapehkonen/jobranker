import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from database import connect, initialize_database, list_profiles, load_enabled_profiles, save_profile
from extract_resume_ai import SCHEMA, extract_and_save_resume
from merge_resume_profiles import (
    _paths, delete_resume_profile, load_base_profile, refresh_base_profile,
)


def profile(skill="Python"):
    result = {}
    for name, schema in SCHEMA["properties"].items():
        result[name] = [] if schema["type"] == "array" else "" if schema["type"] == "string" else None
    result["technical_skills"] = [skill]
    result["years_experience"] = 10
    result["work_experience"] = [{
        "company": "Example", "title": "Engineer", "start": "2015", "end": "2025",
        "summary": "Built software", "highlights": ["Built services"],
    }]
    return result


def stored_result():
    result = profile()
    result["technical_skills"].append("SQL")
    return {"profile": result, "provenance": [
        {"path": path, "source_profiles": ["backend"] if path == "/technical_skills/0"
         else ["cloud"] if path == "/technical_skills/1" else ["backend", "cloud"]}
        for path in sorted(_paths(result))
    ]}


def merged_result():
    stored = stored_result()
    sources = {item["path"]: item["source_profiles"] for item in stored["provenance"]}
    result = {}
    for field, value in stored["profile"].items():
        if isinstance(value, list):
            result[field] = [
                {"value": item, "source_profiles": sources[f"/{field}/{index}"]}
                for index, item in enumerate(value)
            ]
        else:
            result[field] = {"value": value, "source_profiles": sources.get(f"/{field}", [])}
    return result


class FakeResponses:
    def __init__(self, result=None, callback=None):
        self.result = result
        self.callback = callback
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.callback:
            self.callback()
        if isinstance(self.result, Exception):
            raise self.result
        return SimpleNamespace(output_text=json.dumps(self.result))


class BaseProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "test.db"
        initialize_database(self.db)

    def save(self, name, value=None):
        return save_profile(name, "original resume", value or profile(), database_file=self.db)

    def load(self, **kwargs):
        return load_base_profile(database_file=self.db, **kwargs)

    def refresh(self, result=None, callback=None, **kwargs):
        responses = FakeResponses(result, callback)
        value = refresh_base_profile(SimpleNamespace(responses=responses), database_file=self.db, **kwargs)
        return value, responses.calls

    def test_single_profile_copies_without_ai_and_is_separate(self):
        saved = self.save("backend")
        base, calls = self.refresh()
        self.assertEqual([], calls)
        self.assertEqual(profile(), base["profile"])
        self.assertEqual({"backend": saved["profile_hash"]}, base["sources"])
        self.assertEqual("ready", base["status"])
        self.assertEqual({"backend": profile()}, load_enabled_profiles(database_file=self.db))
        self.assertEqual(1, len(list_profiles(database_file=self.db)))
        self.assertTrue(all(p["source_profiles"] == ["backend"] for p in base["provenance"]))

    def test_multiple_profiles_use_original_sources_and_cache(self):
        self.save("backend")
        self.save("cloud", profile("SQL"))
        base, calls = self.refresh(merged_result())
        self.assertEqual(1, len(calls))
        self.assertEqual({"backend": profile(), "cloud": profile("SQL")},
                         json.loads(calls[0]["input"][1]["content"]))
        self.assertEqual(stored_result()["profile"], base["profile"])
        same, calls = self.refresh(RuntimeError("must not call"))
        self.assertEqual(base, same)
        self.assertEqual([], calls)
        self.save("cloud", profile("SQL"))
        _, calls = self.refresh(RuntimeError("must not call"))
        self.assertEqual([], calls)
        _, calls = self.refresh(merged_result(), force=True)
        self.assertEqual(1, len(calls))

    def test_disabled_resume_is_included_in_base(self):
        self.save("backend")
        self.save("cloud", profile("SQL"))
        with connect(self.db) as db:
            db.execute("UPDATE profiles SET enabled = 0 WHERE profile_name = 'cloud'")
        base, _ = self.refresh(merged_result())
        self.assertEqual({"backend", "cloud"}, set(base["sources"]))
        self.assertEqual({"backend"}, set(load_enabled_profiles(database_file=self.db)))

    def test_failed_refresh_preserves_old_base_and_marks_stale(self):
        self.save("backend")
        previous, _ = self.refresh()
        self.save("cloud", profile("SQL"))
        self.assertIsNone(self.load())
        with self.assertRaisesRegex(RuntimeError, "offline"):
            self.refresh(RuntimeError("offline"))
        stale = self.load(allow_stale=True)
        self.assertEqual(previous["profile"], stale["profile"])
        self.assertEqual(previous["sources"], stale["sources"])
        self.assertEqual("stale", stale["status"])
        self.assertEqual("offline", stale["error"])
        self.assertIsNone(self.load())
        self.refresh(merged_result())
        self.assertEqual("ready", self.load()["status"])

    def test_source_change_during_merge_cannot_publish_outdated_result(self):
        self.save("backend")
        self.save("cloud", profile("SQL"))
        with self.assertRaisesRegex(RuntimeError, "changed during merge"):
            self.refresh(merged_result(), callback=lambda: self.save("cloud", profile("Rust")))
        self.assertIsNone(self.load())
        self.assertEqual("stale", self.load(allow_stale=True)["status"])

    def test_invalid_ai_output_and_provenance_are_rejected(self):
        self.save("backend")
        self.save("cloud", profile("SQL"))
        missing_field = merged_result()
        del missing_field["technical_skills"]
        missing_provenance = merged_result()
        del missing_provenance["technical_skills"][0]["source_profiles"]
        unknown_source = merged_result()
        unknown_source["technical_skills"][0]["source_profiles"] = ["invented"]
        empty_source = merged_result()
        empty_source["technical_skills"][0]["source_profiles"] = []
        for value in [missing_field, missing_provenance, unknown_source, empty_source]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.refresh(value)
            self.assertIsNone(self.load())

    def test_inline_sources_generate_exact_paths_for_objects_and_scalars(self):
        self.save("backend")
        self.save("cloud", profile("SQL"))
        response = merged_result()
        response["summary"] = {"value": "", "source_profiles": []}
        response["candidate_title"] = {"value": None, "source_profiles": []}
        response["work_experience"][0]["source_profiles"] = ["backend", "backend", "cloud"]
        base, calls = self.refresh(response)
        evidence = {item["path"]: item["source_profiles"] for item in base["provenance"]}
        self.assertEqual(_paths(base["profile"]), set(evidence))
        self.assertEqual(["backend", "cloud"], evidence["/work_experience/0"])
        self.assertEqual(["cloud"], evidence["/technical_skills/1"])
        self.assertEqual([], evidence["/summary"])
        self.assertNotIn("/candidate_title", evidence)
        self.assertEqual(1, len(calls))

    def test_delete_rebuilds_and_last_delete_clears_base(self):
        self.save("backend")
        self.save("cloud", profile("SQL"))
        self.refresh(merged_result())
        base = delete_resume_profile("cloud", database_file=self.db)
        self.assertEqual(profile(), base["profile"])
        self.assertEqual({"backend"}, set(base["sources"]))
        delete_resume_profile("backend", database_file=self.db)
        self.assertIsNone(self.load())
        self.assertIsNone(self.load(allow_stale=True)["profile"])
        with self.assertRaisesRegex(ValueError, "not found"):
            delete_resume_profile("missing", database_file=self.db)

    def test_direct_sql_change_marks_base_stale(self):
        self.save("backend")
        self.refresh()
        with connect(self.db) as db:
            db.execute("UPDATE profiles SET profile_json = ? WHERE profile_name = 'backend'",
                       (json.dumps(profile("Rust")),))
        self.assertIsNone(self.load())
        self.refresh()
        with connect(self.db) as db:
            db.execute("DELETE FROM profiles")
        self.assertIsNone(self.load())

    def test_extraction_saves_and_refreshes_base(self):
        responses = FakeResponses(profile())
        extract_and_save_resume(SimpleNamespace(responses=responses), "backend", "resume",
                                database_file=self.db)
        self.assertEqual(1, len(responses.calls))
        self.assertEqual(profile(), self.load()["profile"])

    def test_extraction_failure_does_not_change_base(self):
        self.save("backend")
        old, _ = self.refresh()
        with self.assertRaisesRegex(RuntimeError, "offline"):
            extract_and_save_resume(SimpleNamespace(responses=FakeResponses(RuntimeError("offline"))),
                                    "backend", "new resume", database_file=self.db)
        self.assertEqual(old, self.load())

    def test_merge_failure_after_extraction_keeps_new_resume(self):
        self.save("backend")
        self.refresh()
        with patch("merge_resume_profiles.merge_profiles", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "was saved"):
                extract_and_save_resume(SimpleNamespace(responses=FakeResponses(profile("SQL"))),
                                        "cloud", "new resume", database_file=self.db)
        self.assertEqual({"backend", "cloud"}, set(load_enabled_profiles(database_file=self.db)))
        self.assertIsNone(self.load())

    def test_merge_usage_is_recorded_in_selected_database(self):
        self.save("backend")
        self.save("cloud", profile("SQL"))
        response = SimpleNamespace(
            output_text=json.dumps(merged_result()), model="gpt-5.4-mini", id="merge-test",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
        )
        with patch.object(FakeResponses, "create", return_value=response):
            self.refresh()
        with connect(self.db) as db:
            row = db.execute("SELECT operation, total_tokens FROM ai_costs").fetchone()
        self.assertEqual("resume_merge", row["operation"])
        self.assertEqual(150, row["total_tokens"])


if __name__ == "__main__":
    unittest.main()
