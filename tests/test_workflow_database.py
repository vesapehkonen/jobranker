import tempfile
import unittest
from pathlib import Path

from database import (
    apply_migrations,
    connect,
    update_application_status,
    update_job_notes,
)


class WorkflowDatabaseTests(unittest.TestCase):
    def test_status_update_creates_event_and_preserves_notes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            apply_migrations(database_file)
            with connect(database_file) as db:
                db.execute(
                    """
                    INSERT INTO jobs (
                        job_uid, application_status, notes, created_at, updated_at
                    ) VALUES ('job-1', 'new', 'Keep this', 'created', 'old')
                    """
                )

            job = update_application_status(
                "job-1",
                "interested",
                database_file=database_file,
                now="updated",
            )

            self.assertEqual("interested", job["application_status"])
            self.assertEqual("Keep this", job["notes"])
            self.assertEqual("updated", job["status_updated_at"])
            with connect(database_file) as db:
                event = db.execute(
                    "SELECT * FROM application_events WHERE job_uid = 'job-1'"
                ).fetchone()
            self.assertEqual("new", event["old_value"])
            self.assertEqual("interested", event["new_value"])

    def test_repeating_same_status_does_not_duplicate_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            apply_migrations(database_file)
            fallback = {"status": "new", "created_at": "created"}
            update_application_status(
                "job-1", "interested", fallback=fallback,
                database_file=database_file, now="first",
            )
            update_application_status(
                "job-1", "interested", fallback=fallback,
                database_file=database_file, now="second",
            )
            with connect(database_file) as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM application_events WHERE job_uid = 'job-1'"
                ).fetchone()[0]
            self.assertEqual(1, count)

    def test_notes_update_can_import_a_legacy_only_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            apply_migrations(database_file)
            job = update_job_notes(
                "legacy-job",
                "Call recruiter",
                fallback={
                    "status": "applied",
                    "notes": "",
                    "title": "Engineer",
                    "url": "https://example.com/job",
                    "created_at": "created",
                },
                database_file=database_file,
                now="updated",
            )

            self.assertEqual("applied", job["application_status"])
            self.assertEqual("Call recruiter", job["notes"])
            self.assertEqual("Engineer", job["page_title"])
            self.assertEqual("created", job["created_at"])


if __name__ == "__main__":
    unittest.main()
