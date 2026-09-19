import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import (capture_job_record, connect, initialize_database, list_job_summaries,
                      retry_failed_queue_item, save_profile)
from job_matching.filtering import filter_description, evaluate_extraction, adapt_base_profile
from merge_resume_profiles import refresh_base_profile
from report_data import read_job
from worker import run_once

DESCRIPTION = ("Requirements\nWe are looking for an engineer to build and maintain software services. "
               "You will work with our team to design reliable systems and deliver improvements for customers.\n")


def base_profile():
    return {"status": "ready", "sources": {"backend": "hash"}, "merged_at": "now",
            "profile": {"years_experience": 10, "education": [{"degree": "Bachelor of Science", "school": "Example"}],
                        "technical_skills": ["Python", "PostgreSQL", "AWS"]}}


class FilterRuleTests(unittest.TestCase):
    def test_education_experience_and_technology_failures_all_recorded(self):
        result = filter_description(DESCRIPTION + "Master's degree required.\nMinimum 12 years of engineering experience.\nJava, Kotlin, Spring Boot.", base_profile())
        self.assertEqual("filtered_out", result["outcome"])
        self.assertEqual({"education_not_met", "experience_not_met", "technology_coverage_low"},
                         {r["code"] for r in result["reasons"]})
        self.assertEqual("high", result["comparison"]["technology"]["confidence"])
        self.assertTrue(result["extraction"]["education"]["mentions"])

    def test_low_technology_count_does_not_override_education(self):
        result = filter_description(DESCRIPTION + "Master's degree required.\nJava.", base_profile())
        self.assertEqual(["education_not_met"], [r["code"] for r in result["reasons"]])

    def test_low_confidence_and_sufficient_coverage_pass(self):
        for technologies in ("", "Java", "Java and Kotlin", "Python, Java, Kotlin"):
            with self.subTest(technologies=technologies):
                result = filter_description(DESCRIPTION + technologies, base_profile())
                self.assertEqual("passed", result["outcome"])

    def test_preferred_unspecified_and_equivalent_education_pass(self):
        for requirement in ("Master's degree preferred.", "Master's degree.",
                            "Master's degree or equivalent professional experience required.",
                            "20 years of engineering experience preferred."):
            with self.subTest(requirement=requirement):
                self.assertEqual("passed", filter_description(DESCRIPTION.replace("Requirements", "Responsibilities") + requirement, base_profile())["outcome"])

    def test_unknown_profile_values_do_not_reject(self):
        base = base_profile()
        base["profile"].update(education=[], years_experience=None)
        self.assertEqual("passed", filter_description(DESCRIPTION + "Master's degree required. Minimum 20 years of engineering experience.", base)["outcome"])

    def test_threshold_boundaries_use_unrounded_values(self):
        profile = {"technologies": ["t0", "t1", "t2"], "education": {"highest_level": "bachelor"},
                   "experience": {"total_years": 10}}
        job = {"technologies": [f"t{i}" for i in range(20)], "education": {"minimum_level": None},
               "experience": {"minimum_years": 11.5}}
        self.assertEqual([], evaluate_extraction(job, profile)[1])
        job["experience"]["minimum_years"] = 11.50001
        self.assertEqual("experience_not_met", evaluate_extraction(job, profile)[1][0]["code"])
        job["experience"]["minimum_years"] = None
        job["technologies"] = [f"t{i}" for i in range(1001)]
        profile["technologies"] = [f"t{i}" for i in range(150)]
        comparison, reasons = evaluate_extraction(job, profile)
        self.assertEqual(0.15, comparison["technology"]["coverage"])
        self.assertEqual("technology_coverage_low", reasons[0]["code"])

    def test_missing_invalid_descriptions_filter_and_bad_base_errors(self):
        for description, code in [("", "missing_description"), ("View open positions", "invalid_description")]:
            self.assertEqual(code, filter_description(description, base_profile())["reasons"][0]["code"])
        for base in (None, {**base_profile(), "status": "stale"}):
            with self.assertRaisesRegex(ValueError, "current merged base"):
                filter_description(DESCRIPTION, base)

    def test_profile_aliases_and_abbreviated_degree_normalized(self):
        base = base_profile()["profile"]
        base.update(technical_skills=["Postgres", "K8s", "Go", "C"], education=[{"degree": "BS"}])
        normalized = adapt_base_profile(base)
        self.assertEqual("bachelor", normalized["education"]["highest_level"])
        self.assertEqual({"PostgreSQL", "Kubernetes", "Go", "C"}, {t["name"] for t in normalized["technologies"]})


class FilterWorkerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "test.db"
        initialize_database(self.db)
        save_profile("backend", "resume", base_profile()["profile"], database_file=self.db)
        refresh_base_profile(database_file=self.db)
        self.ai = patch("worker.OpenAI").start()
        self.addCleanup(patch.stopall)
        self.output = io.StringIO()

    def run_job(self, text):
        capture_job_record("job", {"text": text, "title": "Engineer"}, database_file=self.db)
        with contextlib.redirect_stdout(self.output):
            run_once(database_file=self.db)
        with connect(self.db) as db:
            queue = dict(db.execute("SELECT * FROM queue_items WHERE job_uid='job'").fetchone())
            evaluations = [dict(r) for r in db.execute("SELECT * FROM local_filter_evaluations WHERE job_uid='job' ORDER BY id")]
        return queue, evaluations

    def test_invalid_and_missing_jobs_saved_completed_without_ai(self):
        queue, evaluations = self.run_job("")
        self.assertEqual(("done", "filtered_out"), (queue["status"], queue["phase"]))
        evaluation = json.loads(evaluations[0]["evaluation_json"])
        self.assertEqual("missing_description", evaluation["reasons"][0]["code"])
        self.ai.assert_not_called()
        summary = list_job_summaries(database_file=self.db, show_filtered=True)["items"][0]
        self.assertEqual("filtered_out", summary["local_filter_outcome"])
        self.assertEqual("new", summary["application_status"])
        with patch("report_data.connect", lambda: connect(self.db)):
            self.assertEqual(evaluation, read_job("job")["local_filter"])
        self.assertEqual("queued", retry_failed_queue_item("job", database_file=self.db))
        with contextlib.redirect_stdout(self.output):
            run_once(database_file=self.db)
        with connect(self.db) as db:
            self.assertEqual(2, db.execute("SELECT COUNT(*) FROM local_filter_evaluations").fetchone()[0])

    def test_invalid_capture_finishes_without_ai(self):
        queue, evaluations = self.run_job("View open positions")
        self.assertEqual("filtered_out", queue["phase"])
        self.assertEqual("invalid_description", json.loads(evaluations[0]["evaluation_json"])["reasons"][0]["code"])
        self.ai.assert_not_called()

    def test_long_news_capture_is_filtered_before_ai(self):
        queue, evaluations = self.run_job("Latest news. Sports, weather and city updates. " * 400)
        self.assertEqual("filtered_out", queue["phase"])
        result = json.loads(evaluations[0]["evaluation_json"])
        self.assertEqual("invalid_description", result["reasons"][0]["code"])
        self.assertIn("missing_job_content", result["reasons"][0]["details"])
        self.ai.assert_not_called()

    def test_missing_base_fails_without_ai(self):
        with connect(self.db) as db:
            db.execute("DELETE FROM base_profile")
        queue, evaluations = self.run_job(DESCRIPTION)
        self.assertEqual("failed", queue["status"])
        self.assertIn("Missing or stale base profile", queue["error"])
        self.assertEqual([], evaluations)
        self.ai.assert_not_called()

    def test_rule_rejection_stops_before_ai(self):
        queue, evaluations = self.run_job(DESCRIPTION + "Minimum 20 years of engineering experience.")
        self.assertEqual("filtered_out", queue["phase"])
        self.assertEqual("experience_not_met", json.loads(evaluations[0]["evaluation_json"])["reasons"][0]["code"])
        self.ai.assert_not_called()

    def test_stale_base_and_extraction_failure_are_retryable_errors(self):
        save_profile("backend", "resume", {**base_profile()["profile"], "years_experience": 9}, database_file=self.db)
        queue, evaluations = self.run_job(DESCRIPTION)
        self.assertEqual("failed", queue["status"])
        self.assertIn("stale base profile", queue["error"])
        self.assertEqual([], evaluations)
        self.ai.assert_not_called()
        refresh_base_profile(database_file=self.db)
        retry_failed_queue_item("job", database_file=self.db)
        with patch("job_matching.filtering.extract_job_description", side_effect=RuntimeError("extractor broke")):
            with contextlib.redirect_stdout(self.output):
                run_once(database_file=self.db)
        with connect(self.db) as db:
            queue = db.execute("SELECT * FROM queue_items").fetchone()
        self.assertEqual("failed", queue["status"])
        self.assertIn("extractor broke", queue["error"])
        self.ai.assert_not_called()

    def test_pass_continues_to_extraction_and_resume_ranking(self):
        with (patch("base_ranking.rank_profile", return_value={"overall_fit_score": 80, "reasoning": "Good fit"}),
              patch("worker.extract_job", return_value={"title": "Engineer"}) as extract,
              patch("worker.rank_job", return_value={"ranking": {}, "profile_rankings": {}}) as rank):
            queue, evaluations = self.run_job(DESCRIPTION + "Python, PostgreSQL, AWS.")
        self.assertEqual("done", queue["status"])
        self.assertEqual("done", queue["phase"])
        self.assertEqual("passed", evaluations[0]["outcome"])
        extract.assert_called_once()
        rank.assert_called_once()
        self.assertEqual({"backend"}, set(rank.call_args.args[2]))

    def test_base_change_during_extraction_fails_before_ai(self):
        from job_matching.filtering import extract_job_description
        def change(description):
            result = extract_job_description(description)
            save_profile("backend", "resume", {**base_profile()["profile"], "years_experience": 8}, database_file=self.db)
            return result
        with patch("job_matching.filtering.extract_job_description", side_effect=change):
            queue, evaluations = self.run_job(DESCRIPTION)
        self.assertEqual("failed", queue["status"])
        self.assertIn("changed during local filtering", queue["error"])
        self.assertEqual([], evaluations)
        self.ai.assert_not_called()
