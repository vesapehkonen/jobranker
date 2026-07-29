import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace

from database import (
    capture_job_record,
    claim_next_queue_item,
    complete_queue_item,
    connect,
    fail_queue_item,
    get_job_state,
    initialize_database,
    retry_failed_queue_item,
    save_job_artifact,
    update_queue_phase,
)
from parse import parse_job
from rank_job_ai import rank_job


class SQLitePipelineTests(unittest.TestCase):
    def test_capture_claim_artifacts_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            initialize_database(database_file)
            raw = {"url": "https://example.com/1", "title": "Engineer", "text": "About the job\nBuild things"}
            state, queue_id = capture_job_record("job-1", raw, database_file=database_file)
            self.assertIsNone(state)
            self.assertIsNotNone(queue_id)
            self.assertEqual("queued", get_job_state("job-1", database_file=database_file))

            duplicate_state, duplicate_id = capture_job_record("job-1", raw, database_file=database_file)
            self.assertEqual("queued", duplicate_state)
            self.assertIsNone(duplicate_id)

            item = claim_next_queue_item(database_file=database_file)
            self.assertEqual(queue_id, item["id"])
            self.assertEqual(raw, item["raw"])
            self.assertEqual("processing", get_job_state("job-1", database_file=database_file))

            cleaned = parse_job(raw)
            update_queue_phase(queue_id, "parse", database_file=database_file)
            save_job_artifact("job-1", "cleaned", cleaned, database_file=database_file)
            structured = {"title": "Engineer", "job_source": "Example", "job_id": "1"}
            save_job_artifact("job-1", "structured", structured, database_file=database_file)
            complete_queue_item(queue_id, database_file=database_file)

            with connect(database_file) as db:
                row = db.execute(
                    "SELECT cleaned_json, structured_json FROM job_artifacts WHERE job_uid = 'job-1'"
                ).fetchone()
                job = db.execute("SELECT source, external_job_id FROM jobs WHERE job_uid = 'job-1'").fetchone()
            self.assertIn("Build things", row["cleaned_json"])
            self.assertIn("Engineer", row["structured_json"])
            self.assertEqual(("Example", "1"), tuple(job))
            self.assertEqual("already_processed", get_job_state("job-1", database_file=database_file))

    def test_failure_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            initialize_database(database_file)
            capture_job_record("job-1", {"text": "body"}, database_file=database_file)
            item = claim_next_queue_item(database_file=database_file)
            fail_queue_item(item["id"], "boom", "trace", database_file=database_file)
            self.assertEqual("failed_existing", get_job_state("job-1", database_file=database_file))
            self.assertEqual("queued", retry_failed_queue_item("job-1", database_file=database_file))
            retried = claim_next_queue_item(database_file=database_file)
            self.assertEqual(item["id"], retried["id"])
            self.assertEqual(2, retried["attempt_count"])

    def test_rank_job_accepts_and_returns_dictionaries(self) -> None:
        rankings = {
            "backend": {
                "overall_fit_score": 0,
                "recommendation": "no",
                "scores": {
                    "technical_skill_fit": 80,
                    "role_experience_fit": 80,
                    "domain_fit": 80,
                    "seniority_fit": 80,
                    "resume_evidence_strength": 80,
                },
            },
            "cloud": {
                "overall_fit_score": 0,
                "recommendation": "no",
                "scores": {
                    "technical_skill_fit": 60,
                    "role_experience_fit": 60,
                    "domain_fit": 60,
                    "seniority_fit": 60,
                    "resume_evidence_strength": 60,
                },
            },
        }
        response = SimpleNamespace(
            output_text=json.dumps({
                "rankings": [
                    {"profile_name": name, "ranking": ranking}
                    for name, ranking in rankings.items()
                ]
            }),
            usage=None,
        )
        responses = SimpleNamespace(create=lambda **kwargs: response)
        client = SimpleNamespace(responses=responses)
        result = rank_job(
            client, {"title": "Engineer"}, {"backend": {}, "cloud": {}}
        )
        self.assertEqual("backend", result["recommended_profile"])
        self.assertEqual({"backend": 80, "cloud": 60}, result["profile_scores"])


if __name__ == "__main__":
    unittest.main()
