import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import capture_job_record, complete_queue_item, connect
from generate_report import read_ranked_jobs


class SQLiteReportTests(unittest.TestCase):
    def test_pending_and_completed_jobs_are_built_from_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
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

            with patch("generate_report.connect", side_effect=lambda: connect(database_file)):
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
