from __future__ import annotations

import sqlite3
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_FILE = BASE_DIR / "data" / "jobranker.db"
DEFAULT_MIGRATIONS_DIR = BASE_DIR / "migrations"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(database_file: Path | str = DEFAULT_DATABASE_FILE) -> sqlite3.Connection:
    database_file = Path(database_file)
    database_file.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_file, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def migration_files(
    migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
) -> Iterator[Path]:
    directory = Path(migrations_dir)
    if not directory.exists():
        raise FileNotFoundError(f"Migration directory not found: {directory}")
    yield from sorted(directory.glob("*.sql"))


def apply_migrations(
    database_file: Path | str = DEFAULT_DATABASE_FILE,
    migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
) -> list[str]:
    """Apply unapplied SQL files and return the versions applied this call."""
    applied: list[str] = []

    with connect(database_file) as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

        for migration_file in migration_files(migrations_dir):
            version = migration_file.name
            exists = db.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if exists:
                continue

            # executescript commits implicitly, so each migration records itself
            # in the same script to avoid a schema without a migration marker.
            quoted_version = version.replace("'", "''")
            quoted_time = utc_now().replace("'", "''")
            script = migration_file.read_text(encoding="utf-8")
            db.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{script}\n"
                "INSERT INTO schema_migrations(version, applied_at) "
                f"VALUES ('{quoted_version}', '{quoted_time}');\n"
                "COMMIT;"
            )
            applied.append(version)

    return applied


def initialize_database(
    database_file: Path | str = DEFAULT_DATABASE_FILE,
) -> list[str]:
    return apply_migrations(database_file)


def _ensure_workflow_job(
    db: sqlite3.Connection,
    job_uid: str,
    fallback: dict[str, Any],
    now: str,
) -> sqlite3.Row:
    existing = db.execute(
        "SELECT * FROM jobs WHERE job_uid = ?", (job_uid,)
    ).fetchone()
    if existing:
        return existing

    db.execute(
        """
        INSERT INTO jobs (
            job_uid, original_url, page_title, application_status, notes,
            created_at, updated_at, status_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_uid,
            fallback.get("url"),
            fallback.get("title"),
            fallback.get("status", "new"),
            str(fallback.get("notes", "")),
            fallback.get("created_at") or now,
            fallback.get("updated_at") or now,
            fallback.get("status_updated_at"),
        ),
    )
    return db.execute(
        "SELECT * FROM jobs WHERE job_uid = ?", (job_uid,)
    ).fetchone()


def update_application_status(
    job_uid: str,
    status: str,
    *,
    fallback: dict[str, Any] | None = None,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
    now: str | None = None,
) -> dict[str, Any]:
    """Update status transactionally, creating a legacy-only job if needed."""
    apply_migrations(database_file)
    fallback = fallback or {}
    now = now or utc_now()

    with connect(database_file) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = _ensure_workflow_job(db, job_uid, fallback, now)
        old_status = existing["application_status"]
        db.execute(
            """
            UPDATE jobs
            SET application_status = ?, status_updated_at = ?, updated_at = ?
            WHERE job_uid = ?
            """,
            (status, now, now, job_uid),
        )
        if old_status != status:
            db.execute(
                """
                INSERT INTO application_events (
                    job_uid, event_type, old_value, new_value, created_at
                ) VALUES (?, 'status_changed', ?, ?, ?)
                """,
                (job_uid, old_status, status, now),
            )
        row = db.execute(
            "SELECT * FROM jobs WHERE job_uid = ?", (job_uid,)
        ).fetchone()
        db.commit()
    return dict(row)


def update_job_notes(
    job_uid: str,
    notes: str,
    *,
    fallback: dict[str, Any] | None = None,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
    now: str | None = None,
) -> dict[str, Any]:
    """Update notes transactionally, creating a legacy-only job if needed."""
    apply_migrations(database_file)
    fallback = fallback or {}
    now = now or utc_now()

    with connect(database_file) as db:
        db.execute("BEGIN IMMEDIATE")
        _ensure_workflow_job(db, job_uid, fallback, now)
        db.execute(
            "UPDATE jobs SET notes = ?, updated_at = ? WHERE job_uid = ?",
            (notes, now, job_uid),
        )
        row = db.execute(
            "SELECT * FROM jobs WHERE job_uid = ?", (job_uid,)
        ).fetchone()
        db.commit()
    return dict(row)


def _decode_json(value: str | None) -> Any:
    return json.loads(value) if value else None


def capture_job_record(
    job_uid: str,
    payload: dict[str, Any],
    *,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
) -> tuple[str | None, int | None]:
    """Atomically insert a job, its raw artifact, and a pending queue row."""
    apply_migrations(database_file)
    now = utc_now()
    with connect(database_file) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT 1 FROM jobs WHERE job_uid = ?", (job_uid,)
        ).fetchone()
        if existing:
            state = get_job_state(job_uid, database_file=database_file, db=db)
            db.commit()
            return state or "already_processed", None

        db.execute(
            """
            INSERT INTO jobs (
                job_uid, original_url, page_title, application_status,
                notes, created_at, updated_at
            ) VALUES (?, ?, ?, 'new', '', ?, ?)
            """,
            (job_uid, payload.get("url"), payload.get("title"), now, now),
        )
        db.execute(
            """
            INSERT INTO job_artifacts (job_uid, raw_json, raw_updated_at)
            VALUES (?, ?, ?)
            """,
            (job_uid, json.dumps(payload, ensure_ascii=False), now),
        )
        cursor = db.execute(
            """
            INSERT INTO queue_items (
                job_uid, status, phase, available_at, payload_json,
                created_at, updated_at
            ) VALUES (?, 'pending', 'queued', ?, ?, ?, ?)
            """,
            (job_uid, now, json.dumps({"title": payload.get("title"), "url": payload.get("url")}), now, now),
        )
        queue_id = cursor.lastrowid
        db.commit()
    return None, queue_id


def get_job_state(
    job_uid: str,
    *,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
    db: sqlite3.Connection | None = None,
) -> str | None:
    owns_connection = db is None
    db = db or connect(database_file)
    try:
        row = db.execute(
            "SELECT status FROM queue_items WHERE job_uid = ? ORDER BY id DESC LIMIT 1",
            (job_uid,),
        ).fetchone()
        if row:
            return {
                "pending": "queued",
                "processing": "processing",
                "failed": "failed_existing",
                "done": "already_processed",
            }[row["status"]]
        artifact = db.execute(
            "SELECT ranked_json FROM job_artifacts WHERE job_uid = ?", (job_uid,)
        ).fetchone()
        if artifact and artifact["ranked_json"]:
            return "already_processed"
        return None
    finally:
        if owns_connection:
            db.close()


def claim_next_queue_item(
    *,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
    lease_seconds: int = 900,
) -> dict[str, Any] | None:
    apply_migrations(database_file)
    now = utc_now()
    lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
    with connect(database_file) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """
            UPDATE queue_items
            SET status = 'pending', phase = 'queued', claimed_at = NULL,
                lease_expires_at = NULL, available_at = ?, updated_at = ?
            WHERE status = 'processing' AND lease_expires_at < ?
            """,
            (now, now, now),
        )
        row = db.execute(
            """
            SELECT id FROM queue_items
            WHERE status = 'pending' AND available_at <= ?
            ORDER BY created_at, id LIMIT 1
            """,
            (now,),
        ).fetchone()
        if not row:
            db.commit()
            return None
        cursor = db.execute(
            """
            UPDATE queue_items
            SET status = 'processing', phase = 'started', claimed_at = ?,
                lease_expires_at = ?, attempt_count = attempt_count + 1,
                error = NULL, traceback = NULL, updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, lease_until, now, row["id"]),
        )
        if cursor.rowcount != 1:
            db.rollback()
            return None
        item = db.execute(
            """
            SELECT q.*, a.raw_json FROM queue_items q
            JOIN job_artifacts a ON a.job_uid = q.job_uid
            WHERE q.id = ?
            """,
            (row["id"],),
        ).fetchone()
        db.commit()
    result = dict(item)
    result["raw"] = _decode_json(result.pop("raw_json"))
    return result


def update_queue_phase(
    queue_id: int,
    phase: str,
    *,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
    lease_seconds: int = 900,
) -> None:
    now = utc_now()
    lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
    with connect(database_file) as db:
        cursor = db.execute(
            """
            UPDATE queue_items SET phase = ?, lease_expires_at = ?, updated_at = ?
            WHERE id = ? AND status = 'processing'
            """,
            (phase, lease_until, now, queue_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Queue item {queue_id} is not processing")


def save_job_artifact(
    job_uid: str,
    artifact: str,
    value: dict[str, Any],
    *,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
) -> None:
    if artifact not in {"raw", "cleaned", "structured", "ranked"}:
        raise ValueError(f"Invalid artifact type: {artifact}")
    now = utc_now()
    with connect(database_file) as db:
        db.execute(
            f"""
            UPDATE job_artifacts
            SET {artifact}_json = ?, {artifact}_updated_at = ?
            WHERE job_uid = ?
            """,
            (json.dumps(value, ensure_ascii=False), now, job_uid),
        )
        if artifact == "structured":
            db.execute(
                """
                UPDATE jobs SET source = ?, external_job_id = ?,
                    original_url = COALESCE(?, original_url),
                    page_title = COALESCE(?, page_title), updated_at = ?
                WHERE job_uid = ?
                """,
                (value.get("job_source"), value.get("job_id"), value.get("job_url"), value.get("title"), now, job_uid),
            )
        if artifact == "ranked":
            for profile_name, ranking in value.get("profile_rankings", {}).items():
                db.execute(
                    """
                    INSERT INTO profile_rankings (
                        job_uid, profile_name, score, ranking_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(job_uid, profile_name) DO UPDATE SET
                        score = excluded.score,
                        ranking_json = excluded.ranking_json,
                        created_at = excluded.created_at
                    """,
                    (job_uid, profile_name, ranking.get("overall_fit_score"), json.dumps(ranking, ensure_ascii=False), now),
                )


def load_enabled_profiles(
    *, database_file: Path | str = DEFAULT_DATABASE_FILE,
) -> dict[str, dict[str, Any]]:
    with connect(database_file) as db:
        rows = db.execute(
            "SELECT profile_name, profile_json FROM profiles WHERE enabled = 1 ORDER BY profile_name"
        ).fetchall()
    profiles = {row["profile_name"]: json.loads(row["profile_json"]) for row in rows}
    if not profiles:
        raise FileNotFoundError("No enabled resume profiles found in SQLite")
    return profiles


def complete_queue_item(
    queue_id: int,
    *, database_file: Path | str = DEFAULT_DATABASE_FILE,
) -> None:
    now = utc_now()
    with connect(database_file) as db:
        cursor = db.execute(
            """
            UPDATE queue_items SET status = 'done', phase = 'done',
                finished_at = ?, lease_expires_at = NULL, updated_at = ?
            WHERE id = ? AND status = 'processing'
            """,
            (now, now, queue_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Queue item {queue_id} is not processing")


def fail_queue_item(
    queue_id: int,
    error: str,
    traceback_text: str,
    *, database_file: Path | str = DEFAULT_DATABASE_FILE,
) -> None:
    now = utc_now()
    with connect(database_file) as db:
        db.execute(
            """
            UPDATE queue_items SET status = 'failed', phase = 'failed',
                error = ?, traceback = ?, finished_at = ?,
                lease_expires_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (error, traceback_text, now, now, queue_id),
        )


def latest_queue_item(
    job_uid: str, *, database_file: Path | str = DEFAULT_DATABASE_FILE
) -> dict[str, Any] | None:
    with connect(database_file) as db:
        row = db.execute(
            "SELECT * FROM queue_items WHERE job_uid = ? ORDER BY id DESC LIMIT 1",
            (job_uid,),
        ).fetchone()
    return dict(row) if row else None


def queue_counts(
    *, database_file: Path | str = DEFAULT_DATABASE_FILE
) -> dict[str, int]:
    result = {state: 0 for state in ("pending", "processing", "done", "failed")}
    with connect(database_file) as db:
        for row in db.execute("SELECT status, COUNT(*) count FROM queue_items GROUP BY status"):
            result[row["status"]] = row["count"]
    return result


def retry_failed_queue_item(
    job_uid: str, *, database_file: Path | str = DEFAULT_DATABASE_FILE
) -> str:
    apply_migrations(database_file)
    now = utc_now()
    with connect(database_file) as db:
        db.execute("BEGIN IMMEDIATE")
        active = db.execute(
            "SELECT 1 FROM queue_items WHERE job_uid = ? AND status IN ('pending', 'processing')",
            (job_uid,),
        ).fetchone()
        if active:
            db.commit()
            return "active"
        failed = db.execute(
            "SELECT id FROM queue_items WHERE job_uid = ? AND status = 'failed' ORDER BY id DESC LIMIT 1",
            (job_uid,),
        ).fetchone()
        if not failed:
            db.commit()
            return "not_found"
        db.execute(
            """
            UPDATE queue_items SET status = 'pending', phase = 'queued',
                available_at = ?, claimed_at = NULL, lease_expires_at = NULL,
                finished_at = NULL, error = NULL, traceback = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now, now, failed["id"]),
        )
        db.commit()
    return "queued"


def save_profile(
    profile_name: str,
    resume_text: str,
    profile: dict[str, Any],
    *,
    database_file: Path | str = DEFAULT_DATABASE_FILE,
) -> dict[str, Any]:
    """Create or replace a resume profile in SQLite."""
    profile_name = profile_name.strip()
    if not profile_name:
        raise ValueError("Profile name must not be empty")
    if not isinstance(profile, dict) or not profile:
        raise ValueError("Profile must be a non-empty dictionary")

    apply_migrations(database_file)
    now = utc_now()
    profile_json = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    profile_hash = hashlib.sha256(profile_json.encode("utf-8")).hexdigest()
    with connect(database_file) as db:
        db.execute(
            """
            INSERT INTO profiles (
                profile_name, resume_text, profile_json, profile_hash,
                enabled, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(profile_name) DO UPDATE SET
                resume_text = excluded.resume_text,
                profile_json = excluded.profile_json,
                profile_hash = excluded.profile_hash,
                updated_at = excluded.updated_at
            """,
            (profile_name, resume_text, profile_json, profile_hash, now),
        )
        row = db.execute(
            """
            SELECT profile_name, profile_hash, enabled, updated_at
            FROM profiles WHERE profile_name = ?
            """,
            (profile_name,),
        ).fetchone()
    return dict(row)


def list_profiles(
    *, database_file: Path | str = DEFAULT_DATABASE_FILE
) -> list[dict[str, Any]]:
    with connect(database_file) as db:
        rows = db.execute(
            """
            SELECT profile_name, profile_hash, enabled, updated_at
            FROM profiles ORDER BY profile_name
            """
        ).fetchall()
    return [dict(row) for row in rows]
