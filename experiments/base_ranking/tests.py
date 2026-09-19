import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from database import capture_job_record, connect, initialize_database, save_profile, save_job_artifact
from merge_resume_profiles import refresh_base_profile
from rank_job_ai import WEIGHTS
from .run import prepare, run_comparison


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db = self.root / "test.db"
        self.output = self.root / "output"
        self.output.mkdir()
        initialize_database(self.db)
        save_profile("backend", "resume", {"technical_skills": ["Python"]}, database_file=self.db)
        refresh_base_profile(database_file=self.db)
        for uid, status, score, phase in (("applied", "applied", 90, "done"),
                                         ("border", "new", 74, "base_filtered"),
                                         ("filtered", "new", 40, "base_filtered"),
                                         ("other", "new", 90, "done")):
            capture_job_record(uid, {"title": uid}, application_status=status, database_file=self.db)
            save_job_artifact(uid, "structured", {"title": uid}, database_file=self.db)
            with connect(self.db) as db:
                db.execute("UPDATE queue_items SET phase=? WHERE job_uid=?", (phase, uid))
                db.execute("INSERT INTO base_rank_evaluations (job_uid,outcome,evaluation_json,created_at) VALUES (?, 'passed', ?, 'now')",
                           (uid, json.dumps({"score": score})))
        capture_job_record("no-extraction", {"title": "empty"}, database_file=self.db)

    def client(self, calls, fail_mini=False):
        def create(**kwargs):
            calls.append(kwargs)
            if fail_mini and kwargs["model"] == "mini":
                raise RuntimeError("offline")
            score = 70 if kwargs["model"] == "gpt-5.4-nano" else 80
            value = {"overall_fit_score": score, "scores": {key: score for key in WEIGHTS}, "reasoning": "Evidence"}
            return SimpleNamespace(output_text=json.dumps(value), model=kwargs["model"], id=str(len(calls)),
                                   usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}))
        return SimpleNamespace(responses=SimpleNamespace(create=create))

    def compare(self, manifest, calls, mini="gpt-5.4-mini", fail=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_comparison(manifest, self.output, "gpt-5.4-nano", mini, lambda: self.client(calls, fail))

    def test_sample_includes_groups_and_freezes_inputs(self):
        manifest = prepare(self.db, self.output, 4, 42)
        self.assertEqual({"applied", "border", "filtered", "other"}, {j["job_uid"] for j in manifest["jobs"]})
        self.assertEqual(manifest, prepare(self.db, self.output, 1, 99))
        with connect(self.db) as db:
            db.execute("UPDATE base_profile SET status='stale'")
        self.assertEqual(manifest, prepare(self.db, self.output, 4, 42))

    def test_cached_run_reports_disagreements_without_production_writes(self):
        manifest = prepare(self.db, self.output, 4, 42)
        before = self.db.read_bytes()
        calls = []
        rows, summary = self.compare(manifest, calls)
        self.assertEqual(8, len(calls))
        self.assertEqual(4, summary["disagreements"])
        self.assertEqual(4, summary["thresholds"][-1]["mini_pass_nano_reject"])
        self.assertEqual(0, summary["thresholds"][0]["nano_rejected"])
        self.assertEqual(1, summary["thresholds"][-1]["applied_jobs_rejected"])
        self.assertGreater(rows[0]["nano_cost_usd"], 0)
        rows2, summary2 = self.compare(manifest, calls)
        self.assertEqual(rows, rows2)
        self.assertEqual(8, len(calls))
        self.assertEqual(8, summary2["cache_hits_this_run"])
        self.assertEqual(before, self.db.read_bytes())
        with connect(self.db) as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM ai_costs").fetchone()[0])
        self.assertTrue((self.output / "disagreements.csv").exists())

    def test_changed_model_invalidates_only_its_cached_requests(self):
        manifest = prepare(self.db, self.output, 1, 42)
        calls = []
        self.compare(manifest, calls)
        _, summary = self.compare(manifest, calls, mini="different-mini")
        self.assertEqual(3, len(calls))
        self.assertEqual(1, summary["mini"]["unpriced_results"])

    def test_partial_failure_keeps_completed_response_for_resume(self):
        manifest = prepare(self.db, self.output, 1, 42)
        calls = []
        rows, _ = self.compare(manifest, calls, mini="mini", fail=True)
        self.assertIn("offline", rows[0]["error"])
        _, summary = self.compare(manifest, calls, mini="mini")
        self.assertEqual(1, summary["completed_pairs"])
        self.assertEqual(3, len(calls))


if __name__ == "__main__":
    unittest.main()
