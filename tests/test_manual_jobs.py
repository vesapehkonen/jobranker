import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import add_manual_job, normalized_web_url, remove_job, set_application_link
from database import (
    capture_job_record,
    connect,
    delete_job,
    initialize_database,
    list_job_summaries,
    save_job_artifact,
    update_job_application_url,
)


class ManualJobEndpointTests(unittest.TestCase):
    def test_manual_job_uses_unique_id_and_queues_recruiter_metadata(self) -> None:
        with (
            patch("app.uuid.uuid4") as uuid4,
            patch("app.capture_job_record", return_value=(None, 42)) as capture,
            patch("app.update_notes_in_database") as update_notes,
        ):
            uuid4.return_value.hex = "a" * 32
            response = add_manual_job({
                "text": "Build cloud services",
                "title": "Cloud Engineer",
                "company": "Example Co",
                "recruiter_name": "Alex Recruiter",
                "recruiter_email": "alex@example.com",
                "notes": "Reply by Friday",
            }, None)

        self.assertEqual(200, response.status_code)
        uid, raw = capture.call_args.args
        self.assertEqual("a" * 16, uid)
        self.assertTrue(raw["manual"])
        self.assertIsNone(raw["application_url"])
        self.assertEqual("Recruiter", raw["source"])
        update_notes.assert_called_once_with(uid, "Reply by Friday")

    def test_manual_job_requires_description_and_valid_web_url(self) -> None:
        with self.assertRaises(HTTPException) as missing:
            add_manual_job({"text": "  "}, None)
        self.assertEqual(400, missing.exception.status_code)

        with self.assertRaises(HTTPException) as invalid:
            normalized_web_url("javascript:alert(1)")
        self.assertEqual(400, invalid.exception.status_code)

    def test_application_link_endpoint_reports_unknown_job(self) -> None:
        with patch("app.update_job_application_url", return_value=False):
            with self.assertRaises(HTTPException) as missing:
                set_application_link("missing", {"application_url": "https://example.com"}, None)
        self.assertEqual(404, missing.exception.status_code)

    def test_delete_endpoint_reports_unknown_job(self) -> None:
        with patch("app.delete_job", return_value=False):
            with self.assertRaises(HTTPException) as missing:
                remove_job("missing", None)
        self.assertEqual(404, missing.exception.status_code)


class ManualJobDatabaseTests(unittest.TestCase):
    def test_application_url_can_be_added_to_url_less_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobs.db"
            initialize_database(database_file)
            capture_job_record(
                "manual-1",
                {
                    "manual": True,
                    "text": "Job description",
                    "title": "Engineer",
                    "source": "Recruiter",
                    "application_url": None,
                },
                database_file=database_file,
            )
            save_job_artifact(
                "manual-1",
                "structured",
                {"title": "Engineer", "job_url": "https://inferred.example/apply"},
                database_file=database_file,
            )

            summary = list_job_summaries(
                status="new", database_file=database_file
            )["items"][0]
            self.assertEqual("", summary["url"])

            updated = update_job_application_url(
                "manual-1", "https://example.com/apply", database_file=database_file
            )

            self.assertTrue(updated)
            with connect(database_file) as db:
                job = db.execute(
                    "SELECT original_url, source FROM jobs WHERE job_uid = 'manual-1'"
                ).fetchone()
                artifact = db.execute(
                    "SELECT raw_json FROM job_artifacts WHERE job_uid = 'manual-1'"
                ).fetchone()
            self.assertEqual("https://example.com/apply", job["original_url"])
            self.assertEqual("Recruiter", job["source"])
            self.assertEqual(
                "https://example.com/apply",
                json.loads(artifact["raw_json"])["application_url"],
            )

    def test_delete_job_removes_job_and_cascading_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobs.db"
            initialize_database(database_file)
            capture_job_record(
                "delete-me", {"text": "Job description", "title": "Engineer"},
                database_file=database_file,
            )

            self.assertTrue(delete_job("delete-me", database_file=database_file))
            self.assertFalse(delete_job("delete-me", database_file=database_file))
            with connect(database_file) as db:
                jobs = db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE job_uid = 'delete-me'"
                ).fetchone()[0]
                artifacts = db.execute(
                    "SELECT COUNT(*) FROM job_artifacts WHERE job_uid = 'delete-me'"
                ).fetchone()[0]
                queue_items = db.execute(
                    "SELECT COUNT(*) FROM queue_items WHERE job_uid = 'delete-me'"
                ).fetchone()[0]
            self.assertEqual((0, 0, 0), (jobs, artifacts, queue_items))


if __name__ == "__main__":
    unittest.main()
