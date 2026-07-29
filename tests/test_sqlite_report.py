import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import (
    capture_job_record,
    complete_queue_item,
    connect,
    initialize_database,
    list_job_summaries,
)
from report_data import read_ranked_jobs


class SQLiteReportTests(unittest.TestCase):
    def test_job_summaries_support_search_sort_score_and_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            initialize_database(database_file)
            for uid, title, company, score in (
                ("job-a", "Python Engineer", "Alpha", 90),
                ("job-b", "Java Engineer", "Beta", 70),
                ("job-c", "Python Developer", "Gamma", 80),
            ):
                capture_job_record(
                    uid,
                    {"url": f"https://example.com/{uid}", "title": title},
                    database_file=database_file,
                )
                ranked = {
                    "job": {"title": title, "company": company},
                    "recommended_profile": "backend",
                    "ranking": {
                        "overall_fit_score": score,
                        "recommendation": "good",
                    },
                }
                with connect(database_file) as db:
                    db.execute(
                        "UPDATE job_artifacts SET ranked_json = ? WHERE job_uid = ?",
                        (json.dumps(ranked), uid),
                    )

            result = list_job_summaries(
                search="python",
                status="all",
                sort="score_desc",
                minimum_score=80,
                page=1,
                page_size=1,
                database_file=database_file,
            )
            self.assertEqual(2, result["total_items"])
            self.assertEqual(2, result["total_pages"])
            self.assertEqual("job-a", result["items"][0]["job_uid"])
            self.assertNotIn("search_text", result["items"][0])

    def test_pending_and_completed_jobs_are_built_from_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            initialize_database(database_file)
            capture_job_record(
                "pending-job",
                {"url": "https://example.com/pending", "title": "Pending role", "text": "body"},
                database_file=database_file,
            )
            capture_job_record(
                "done-job",
                {"url": "https://example.com/done", "title": "Raw role", "text": "body"},
                database_file=database_file,
            )
            with connect(database_file) as db:
                queue_id = db.execute(
                    "SELECT id FROM queue_items WHERE job_uid = 'done-job'"
                ).fetchone()[0]
                db.execute(
                    "UPDATE queue_items SET status = 'processing' WHERE id = ?",
                    (queue_id,),
                )
                ranked = {
                    "job": {"title": "Ranked role", "company": "Example Co"},
                    "recommended_profile": "backend",
                    "profile_scores": {"backend": 88},
                    "ranking": {
                        "overall_fit_score": 88,
                        "recommendation": "strong",
                        "matched_strengths": ["Python"],
                    },
                }
                db.execute(
                    "UPDATE job_artifacts SET ranked_json = ? WHERE job_uid = 'done-job'",
                    (json.dumps(ranked),),
                )
            complete_queue_item(queue_id, database_file=database_file)

            with patch("report_data.connect", side_effect=lambda: connect(database_file)):
                jobs = read_ranked_jobs()

            by_uid = {job["job_uid"]: job for job in jobs}
            self.assertEqual("pending", by_uid["pending-job"]["processing_status"])
            self.assertEqual("Pending role", by_uid["pending-job"]["title"])
            self.assertEqual("done", by_uid["done-job"]["processing_status"])
            self.assertEqual(88, by_uid["done-job"]["score"])
            self.assertEqual("Example Co", by_uid["done-job"]["company"])
            self.assertEqual("backend", by_uid["done-job"]["recommended_profile"])


if __name__ == "__main__":
    unittest.main()
