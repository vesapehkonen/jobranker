import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from base_ranking import extraction_key
from database import (capture_job_record, connect, initialize_database, retry_failed_queue_item,
                      save_profile, list_job_summaries)
from merge_resume_profiles import refresh_base_profile
from rank_job_ai import rank_profile, WEIGHTS
from report_data import read_job
from worker import run_once

DESCRIPTION = "Requirements: Python. You will develop software and work with the team to design reliable systems and deliver improvements for customers."


class BaseRankingPipelineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "test.db"
        initialize_database(self.db)
        self.profile = {"years_experience": 10, "education": [], "technical_skills": ["Python"]}
        save_profile("backend", "resume", self.profile, database_file=self.db)
        refresh_base_profile(database_file=self.db)
        capture_job_record("job", {"text": DESCRIPTION, "title": "Engineer"}, database_file=self.db)
        self.client = patch("worker.OpenAI").start()
        self.extract = patch("worker.extract_job", return_value={"title": "Engineer"}).start()
        self.base_rank = patch("base_ranking.rank_profile", return_value={"overall_fit_score": 75, "reasoning": "Relevant skills"}).start()
        self.rank = patch("worker.rank_job", return_value={"ranking": {}, "profile_rankings": {}}).start()
        self.addCleanup(patch.stopall)

    def run_worker(self):
        with contextlib.redirect_stdout(io.StringIO()):
            run_once(database_file=self.db)
        with connect(self.db) as db:
            return dict(db.execute("SELECT * FROM queue_items").fetchone())

    def evaluations(self):
        with connect(self.db) as db:
            return [json.loads(r[0]) for r in db.execute("SELECT evaluation_json FROM base_rank_evaluations ORDER BY id")]

    def test_below_75_filters_and_stores_report_without_resume_ranking(self):
        self.base_rank.return_value = {"overall_fit_score": 74, "reasoning": "Insufficient relevant experience"}
        queue = self.run_worker()
        self.assertEqual(("done", "base_filtered"), (queue["status"], queue["phase"]))
        self.rank.assert_not_called()
        evaluation = self.evaluations()[0]
        self.assertEqual(75, evaluation["threshold"])
        self.assertEqual("filtered_out", evaluation["outcome"])
        self.assertTrue(evaluation["base_sources"])
        summary = list_job_summaries(database_file=self.db, show_filtered=True)["items"][0]
        self.assertEqual(74, summary["base_score"])
        self.assertEqual("new", summary["application_status"])
        with patch("report_data.connect", lambda: connect(self.db)):
            self.assertEqual(evaluation, read_job("job")["base_rank"])
        with connect(self.db) as db:
            artifacts = db.execute("SELECT structured_json, ranked_json FROM job_artifacts").fetchone()
        self.assertIsNotNone(artifacts[0])
        self.assertIsNone(artifacts[1])

    def test_exact_75_passes_to_existing_resume_ranking(self):
        queue = self.run_worker()
        self.assertEqual("done", queue["phase"])
        self.assertEqual("passed", self.evaluations()[0]["outcome"])
        self.rank.assert_called_once()
        self.assertEqual({"backend"}, set(self.rank.call_args.args[2]))
        self.assertEqual(self.profile, self.base_rank.call_args.args[2])
        self.assertEqual("base_rank", self.base_rank.call_args.kwargs["operation"])

    def test_failed_resume_ranking_retry_reuses_extraction_and_base_ranking(self):
        self.rank.side_effect = RuntimeError("ranking unavailable")
        self.assertEqual("failed", self.run_worker()["status"])
        retry_failed_queue_item("job", database_file=self.db)
        self.rank.side_effect = None
        self.assertEqual("done", self.run_worker()["status"])
        self.extract.assert_called_once()
        self.base_rank.assert_called_once()
        self.assertEqual(2, self.rank.call_count)
        self.assertTrue(self.evaluations()[-1]["cached"])

    def test_recheck_filtered_job_reuses_cache(self):
        self.base_rank.return_value = {"overall_fit_score": 50, "reasoning": "Weak fit"}
        self.run_worker()
        self.assertEqual("queued", retry_failed_queue_item("job", database_file=self.db))
        self.run_worker()
        self.extract.assert_called_once()
        self.base_rank.assert_called_once()
        self.assertEqual(2, len(self.evaluations()))

    def test_changed_base_invalidates_only_base_ranking(self):
        self.base_rank.return_value = {"overall_fit_score": 50, "reasoning": "Weak fit"}
        self.run_worker()
        save_profile("backend", "new resume", {**self.profile, "years_experience": 11}, database_file=self.db)
        refresh_base_profile(database_file=self.db)
        retry_failed_queue_item("job", database_file=self.db)
        self.base_rank.return_value = {"overall_fit_score": 80, "reasoning": "Good fit"}
        self.assertEqual("done", self.run_worker()["phase"])
        self.extract.assert_called_once()
        self.assertEqual(2, self.base_rank.call_count)

    def test_changed_description_invalidates_extraction(self):
        self.base_rank.return_value = {"overall_fit_score": 50, "reasoning": "Weak fit"}
        self.run_worker()
        with connect(self.db) as db:
            db.execute("UPDATE job_artifacts SET raw_json=?", (json.dumps({"text": DESCRIPTION + " Additional Python responsibilities."}),))
        retry_failed_queue_item("job", database_file=self.db)
        self.run_worker()
        self.assertEqual(2, self.extract.call_count)

    def test_extraction_prompt_and_model_are_part_of_cache_key(self):
        first = extraction_key({"description_text": "test"}, "prompt")
        self.assertNotEqual(first, extraction_key({"description_text": "test"}, "changed prompt"))
        with patch("base_ranking.JOB_EXTRACT_MODEL", "new-model"):
            self.assertNotEqual(first, extraction_key({"description_text": "test"}, "prompt"))

    def test_invalid_score_is_retryable_and_not_cached(self):
        for score in (-1, 101, None, True, "75", 75.5):
            with self.subTest(score=score):
                self.base_rank.return_value = {"overall_fit_score": score, "reasoning": "Evidence"}
                self.assertEqual("failed", self.run_worker()["status"])
                self.assertEqual([], self.evaluations())
                retry_failed_queue_item("job", database_file=self.db)
        self.rank.assert_not_called()
        self.extract.assert_called_once()

    def test_base_rank_api_failure_preserves_extraction_for_retry(self):
        self.base_rank.side_effect = RuntimeError("API unavailable")
        self.assertEqual("failed", self.run_worker()["status"])
        self.assertEqual([], self.evaluations())
        self.rank.assert_not_called()
        retry_failed_queue_item("job", database_file=self.db)
        self.base_rank.side_effect = None
        self.run_worker()
        self.extract.assert_called_once()

    def test_base_becoming_stale_during_extraction_errors_before_base_call(self):
        def extract(*args, **kwargs):
            save_profile("backend", "changed", {**self.profile, "years_experience": 11}, database_file=self.db)
            return {"title": "Engineer"}
        self.extract.side_effect = extract
        self.assertEqual("failed", self.run_worker()["status"])
        self.base_rank.assert_not_called()
        self.rank.assert_not_called()

    def test_base_change_during_ranking_does_not_publish_or_cache(self):
        def rank(*args, **kwargs):
            save_profile("backend", "changed", {**self.profile, "years_experience": 11}, database_file=self.db)
            return {"overall_fit_score": 50, "reasoning": "Weak fit"}
        self.base_rank.side_effect = rank
        self.assertEqual("failed", self.run_worker()["status"])
        self.assertEqual([], self.evaluations())
        with connect(self.db) as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM job_ai_cache WHERE stage='base_rank'").fetchone()[0])
        self.rank.assert_not_called()


class BaseRankingAPITests(unittest.TestCase):
    def test_validates_dimension_scores_and_tracks_base_cost_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            db_file = Path(directory) / "test.db"
            initialize_database(db_file)
            value = {"overall_fit_score": 10, "scores": {key: 75 for key in WEIGHTS}, "reasoning": "Good evidence"}
            response = SimpleNamespace(output_text=json.dumps(value), id="base-call", model="gpt-5.4-mini",
                                       usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150))
            client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
            ranking = rank_profile(client, "merged_base", {}, {}, operation="base_rank", database_file=db_file)
            self.assertEqual(75, ranking["overall_fit_score"])
            with connect(db_file) as db:
                self.assertEqual("base_rank", db.execute("SELECT operation FROM ai_costs").fetchone()[0])
            value["scores"]["domain_fit"] = 200
            response.output_text = json.dumps(value)
            with self.assertRaisesRegex(ValueError, "between 0 and 100"):
                rank_profile(client, "merged_base", {}, {}, database_file=db_file)
