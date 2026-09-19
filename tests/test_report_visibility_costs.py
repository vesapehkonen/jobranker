import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_costs import track_openai_response
from app import get_jobs
from database import capture_job_record, connect, initialize_database, list_job_summaries
from report_data import read_job, summarize_ai_usage


class ReportVisibilityCostTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "test.db"
        initialize_database(self.db)

    def capture(self, uid, status="done", phase="done", application_status="new"):
        capture_job_record(uid, {"title": "Engineer"}, application_status=application_status, database_file=self.db)
        with connect(self.db) as db:
            db.execute("UPDATE queue_items SET status=?, phase=? WHERE job_uid=?", (status, phase, uid))

    def test_filtering_precedes_pagination_and_keeps_failed_and_legacy_jobs(self):
        for uid, status, phase in (("local", "done", "filtered_out"), ("base", "done", "base_filtered"),
                                   ("failed", "failed", "failed"), ("old", "done", "done"),
                                   ("retry", "pending", "queued")):
            self.capture(uid, status, phase)
        first = list_job_summaries(database_file=self.db, page_size=2)
        second = list_job_summaries(database_file=self.db, page_size=2, page=2)
        self.assertEqual(3, first["total_items"])
        self.assertEqual(2, first["total_pages"])
        self.assertEqual({"failed", "old", "retry"}, {r["job_uid"] for r in first["items"] + second["items"]})
        included = list_job_summaries(database_file=self.db, show_filtered=True)
        self.assertEqual(5, included["total_items"])
        self.assertEqual(3, list_job_summaries(database_file=self.db, status="all")["total_items"])
        self.assertEqual(5, list_job_summaries(database_file=self.db, status="all", show_filtered=True)["total_items"])

    def test_toggle_is_independent_of_application_status(self):
        self.capture("applied", phase="base_filtered", application_status="applied")
        self.assertEqual(0, list_job_summaries(database_file=self.db, status="applied")["total_items"])
        self.assertEqual(1, list_job_summaries(database_file=self.db, status="applied", show_filtered=True)["total_items"])
        with patch("app.list_job_summaries", return_value={}) as summaries:
            get_jobs(show_filtered=True)
        self.assertTrue(summaries.call_args.kwargs["show_filtered"])

    def record(self, uid, response_id, model, operation):
        response = SimpleNamespace(id=response_id, model=model,
                                   usage=SimpleNamespace(input_tokens=100, output_tokens=20, total_tokens=120))
        track_openai_response(response, operation, job_uid=uid, database_file=self.db)

    def test_job_usage_sums_stages_and_retries_without_other_job_costs(self):
        self.capture("job")
        self.capture("other")
        for index, operation in enumerate(("job_extract", "base_rank", "job_rank", "job_rank")):
            self.record("job", str(index), "gpt-5.4-mini", operation)
        self.record("other", "other", "gpt-5.4-mini", "job_rank")
        with patch("report_data.connect", lambda: connect(self.db)):
            usage = read_job("job")["ai_usage"]
        self.assertEqual(4, usage["call_count"])
        self.assertEqual(480, usage["total_tokens"])
        self.assertEqual(400, usage["input_tokens"])
        self.assertEqual(80, usage["output_tokens"])
        self.assertGreater(usage["estimated_cost_usd"], 0)
        self.assertEqual(sum(call["total_cost_usd"] for call in usage["calls"]), usage["estimated_cost_usd"])

    def test_unknown_pricing_never_looks_like_complete_cost(self):
        self.capture("job")
        self.record("job", "known", "gpt-5.4-mini", "job_extract")
        self.record("job", "unknown", "unpriced-model", "base_rank")
        with patch("report_data.connect", lambda: connect(self.db)):
            usage = read_job("job")["ai_usage"]
        self.assertIsNone(usage["estimated_cost_usd"])
        self.assertGreater(usage["known_cost_usd"], 0)
        self.assertEqual(1, usage["unpriced_calls"])
        self.assertEqual(240, usage["total_tokens"])
        self.assertIsNone(summarize_ai_usage([])["estimated_cost_usd"])
        self.assertEqual(0, summarize_ai_usage([])["call_count"])
