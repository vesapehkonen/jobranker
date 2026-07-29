import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from database import apply_migrations, connect
from migrate_files_to_sqlite import migrate


class DatabaseTests(unittest.TestCase):
    def test_simultaneous_migration_initialization_is_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(
                    executor.map(
                        lambda _: apply_migrations(database_file),
                        range(8),
                    )
                )

            self.assertEqual(3, sum(len(result) for result in results))
            with connect(database_file) as db:
                versions = db.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            self.assertEqual(
                [
                    "001_initial.sql",
                    "002_allow_duplicate_source_ids.sql",
                    "003_ai_costs.sql",
                ],
                [row["version"] for row in versions],
            )

    def test_migrations_are_idempotent_and_enable_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"

            self.assertEqual(
                [
                    "001_initial.sql",
                    "002_allow_duplicate_source_ids.sql",
                    "003_ai_costs.sql",
                ],
                apply_migrations(database_file),
            )
            self.assertEqual([], apply_migrations(database_file))

            with connect(database_file) as db:
                self.assertEqual(1, db.execute("PRAGMA foreign_keys").fetchone()[0])
                tables = {
                    row[0]
                    for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertTrue(
                {
                    "jobs", "job_artifacts", "queue_items", "profiles",
                    "profile_rankings", "ai_costs",
                }
                <= tables
            )

    def test_active_queue_item_is_unique_per_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            apply_migrations(database_file)

            with connect(database_file) as db:
                db.execute(
                    """
                    INSERT INTO jobs (
                        job_uid, application_status, notes, created_at, updated_at
                    ) VALUES ('job-1', 'new', '', 'now', 'now')
                    """
                )
                db.execute(
                    """
                    INSERT INTO queue_items (
                        job_uid, status, phase, available_at, created_at, updated_at
                    ) VALUES ('job-1', 'pending', 'queued', 'now', 'now', 'now')
                    """
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        """
                        INSERT INTO queue_items (
                            job_uid, status, phase, available_at, created_at, updated_at
                        ) VALUES ('job-1', 'processing', 'started', 'now', 'now', 'now')
                        """
                    )


class FilesystemImportTests(unittest.TestCase):
    def make_data(self, root: Path) -> Path:
        data = root / "data"
        for name in (
            "raw", "cleaned", "structured", "ranked", "state",
            "profile/backend", "queue/done", "queue/failed",
            "queue/pending", "queue/processing",
        ):
            (data / name).mkdir(parents=True, exist_ok=True)

        uid = "abc123"
        (data / "raw" / f"{uid}.raw.json").write_text(
            json.dumps({"url": "https://example.com/job/1", "title": "Raw title", "text": "body"}),
            encoding="utf-8",
        )
        (data / "cleaned" / f"{uid}.cleaned.json").write_text(
            json.dumps({"url": "https://example.com/job/1", "description_text": "body"}),
            encoding="utf-8",
        )
        (data / "structured" / f"{uid}.structured.json").write_text(
            json.dumps({
                "job_url": "https://example.com/job/1",
                "job_source": "Example",
                "job_id": "1",
                "title": "Structured title",
            }),
            encoding="utf-8",
        )
        ranking = {"overall_fit_score": 81, "recommendation": "strong"}
        (data / "ranked" / f"{uid}.ranked.json").write_text(
            json.dumps({
                "job": {"title": "Structured title"},
                "profile_rankings": {"backend": ranking},
            }),
            encoding="utf-8",
        )
        (data / "state" / "job_status.json").write_text(
            json.dumps({
                uid: {
                    "status": "interested",
                    "notes": "Follow up",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-02T00:00:00+00:00",
                }
            }),
            encoding="utf-8",
        )
        (data / "queue" / "done" / f"{uid}.json").write_text(
            json.dumps({
                "job_uid": uid,
                "status": "done",
                "created_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T01:00:00+00:00",
            }),
            encoding="utf-8",
        )
        (data / "profile" / "backend" / "profile.json").write_text(
            json.dumps({"candidate_title": "Backend engineer"}),
            encoding="utf-8",
        )
        (data / "profile" / "backend" / "resume.txt").write_text(
            "Resume text", encoding="utf-8"
        )
        return data

    def test_imports_and_reimports_filesystem_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = self.make_data(root)
            database_file = root / "jobranker.db"

            first = migrate(data, database_file)
            second = migrate(data, database_file)
            self.assertEqual(first, second)
            self.assertEqual(
                {
                    "jobs": 1,
                    "job_artifacts": 1,
                    "queue_items": 1,
                    "profiles": 1,
                    "profile_rankings": 1,
                },
                second,
            )

            with connect(database_file) as db:
                job = db.execute("SELECT * FROM jobs WHERE job_uid = 'abc123'").fetchone()
                artifacts = db.execute(
                    "SELECT * FROM job_artifacts WHERE job_uid = 'abc123'"
                ).fetchone()
                queue = db.execute(
                    "SELECT * FROM queue_items WHERE job_uid = 'abc123'"
                ).fetchone()

            self.assertEqual("interested", job["application_status"])
            self.assertEqual("Follow up", job["notes"])
            self.assertEqual("Structured title", job["page_title"])
            self.assertEqual("Example", job["source"])
            self.assertEqual("body", json.loads(artifacts["cleaned_json"])["description_text"])
            self.assertEqual("done", queue["status"])


if __name__ == "__main__":
    unittest.main()
