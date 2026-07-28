from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database import DEFAULT_DATABASE_FILE, apply_migrations, connect


ARTIFACT_SUFFIXES = {
    "raw": ".raw.json",
    "cleaned": ".cleaned.json",
    "structured": ".structured.json",
    "ranked": ".ranked.json",
}
QUEUE_STATES = ("done", "failed", "pending", "processing")


def timestamp_for(path: Path | None) -> str:
    timestamp = path.stat().st_mtime if path and path.exists() else datetime.now().timestamp()
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def read_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def artifact_paths(data_dir: Path, job_uid: str) -> dict[str, Path]:
    return {
        name: data_dir / name / f"{job_uid}{suffix}"
        for name, suffix in ARTIFACT_SUFFIXES.items()
    }


def discover_job_uids(data_dir: Path, statuses: dict[str, Any]) -> set[str]:
    job_uids = set(statuses)
    for name, suffix in ARTIFACT_SUFFIXES.items():
        job_uids.update(
            path.name[: -len(suffix)]
            for path in (data_dir / name).glob(f"*{suffix}")
        )
    for state in QUEUE_STATES:
        job_uids.update(path.stem for path in (data_dir / "queue" / state).glob("*.json"))
    return job_uids


def first_value(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def import_job(
    db: sqlite3.Connection,
    data_dir: Path,
    job_uid: str,
    status_data: dict[str, Any],
) -> None:
    paths = artifact_paths(data_dir, job_uid)
    artifacts = {name: read_json(path, {}) for name, path in paths.items()}
    raw = artifacts["raw"]
    cleaned = artifacts["cleaned"]
    structured = artifacts["structured"]
    ranked = artifacts["ranked"]
    ranked_job = ranked.get("job", {}) if isinstance(ranked, dict) else {}

    existing_paths = [path for path in paths.values() if path.exists()]
    fallback_time = timestamp_for(min(existing_paths, key=lambda p: p.stat().st_mtime) if existing_paths else None)
    created_at = status_data.get("created_at") or fallback_time
    updated_at = status_data.get("updated_at") or max(
        (timestamp_for(path) for path in existing_paths),
        default=created_at,
    )

    original_url = first_value(
        structured.get("job_url"),
        ranked_job.get("job_url"),
        raw.get("url"),
        cleaned.get("url"),
        status_data.get("url"),
    )
    page_title = first_value(
        structured.get("title"),
        ranked_job.get("title"),
        raw.get("title"),
        cleaned.get("page_title"),
        status_data.get("title"),
    )
    source = first_value(structured.get("job_source"), ranked_job.get("job_source"))
    external_job_id = first_value(structured.get("job_id"), ranked_job.get("job_id"))

    db.execute(
        """
        INSERT INTO jobs (
            job_uid, original_url, page_title, source, external_job_id,
            application_status, notes, created_at, updated_at, status_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_uid) DO UPDATE SET
            original_url = excluded.original_url,
            page_title = excluded.page_title,
            source = excluded.source,
            external_job_id = excluded.external_job_id,
            application_status = excluded.application_status,
            notes = excluded.notes,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            status_updated_at = excluded.status_updated_at
        """,
        (
            job_uid,
            original_url,
            page_title,
            source,
            external_job_id,
            status_data.get("status", "new"),
            str(status_data.get("notes", "")),
            created_at,
            updated_at,
            status_data.get("status_updated_at"),
        ),
    )

    values: dict[str, Any] = {"job_uid": job_uid}
    for name, path in paths.items():
        values[f"{name}_json"] = json_text(artifacts[name]) if path.exists() else None
        values[f"{name}_updated_at"] = timestamp_for(path) if path.exists() else None

    db.execute(
        """
        INSERT INTO job_artifacts (
            job_uid, raw_json, cleaned_json, structured_json, ranked_json,
            raw_updated_at, cleaned_updated_at, structured_updated_at, ranked_updated_at
        ) VALUES (
            :job_uid, :raw_json, :cleaned_json, :structured_json, :ranked_json,
            :raw_updated_at, :cleaned_updated_at, :structured_updated_at, :ranked_updated_at
        )
        ON CONFLICT(job_uid) DO UPDATE SET
            raw_json = excluded.raw_json,
            cleaned_json = excluded.cleaned_json,
            structured_json = excluded.structured_json,
            ranked_json = excluded.ranked_json,
            raw_updated_at = excluded.raw_updated_at,
            cleaned_updated_at = excluded.cleaned_updated_at,
            structured_updated_at = excluded.structured_updated_at,
            ranked_updated_at = excluded.ranked_updated_at
        """,
        values,
    )


def queue_legacy_key(job_uid: str, item: dict[str, Any], path: Path) -> str:
    attempt_marker = first_value(
        item.get("rerun_queued_at"),
        item.get("retried_at"),
        item.get("created_at"),
    )
    if attempt_marker:
        return f"{job_uid}:{attempt_marker}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f"{job_uid}:{digest}"


def import_queue_items(db: sqlite3.Connection, data_dir: Path) -> None:
    # Finished attempts are imported before active attempts so a rerun represented
    # by both done/<uid>.json and pending/<uid>.json retains both records.
    for state in QUEUE_STATES:
        for path in sorted((data_dir / "queue" / state).glob("*.json")):
            item = read_json(path, {})
            job_uid = item.get("job_uid") or path.stem
            created_at = item.get("created_at") or timestamp_for(path)
            updated_at = first_value(
                item.get("updated_at"),
                item.get("finished_at"),
                item.get("failed_at"),
                timestamp_for(path),
            )
            phase = item.get("processing_phase") or (
                "done" if state == "done" else "failed" if state == "failed" else "queued"
            )

            db.execute(
                """
                INSERT INTO queue_items (
                    job_uid, legacy_key, status, phase, attempt_count,
                    available_at, claimed_at, finished_at, error, traceback,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(legacy_key) DO UPDATE SET
                    status = excluded.status,
                    phase = excluded.phase,
                    attempt_count = excluded.attempt_count,
                    claimed_at = excluded.claimed_at,
                    finished_at = excluded.finished_at,
                    error = excluded.error,
                    traceback = excluded.traceback,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    job_uid,
                    queue_legacy_key(job_uid, item, path),
                    state,
                    phase,
                    int(item.get("attempt_count", 1 if state != "pending" else 0)),
                    item.get("available_at") or created_at,
                    item.get("started_at"),
                    item.get("finished_at") or item.get("failed_at"),
                    item.get("error"),
                    item.get("traceback"),
                    json_text(item),
                    created_at,
                    updated_at,
                ),
            )


def import_profiles(db: sqlite3.Connection, data_dir: Path) -> None:
    for profile_file in sorted((data_dir / "profile").glob("*/profile.json")):
        profile_name = profile_file.parent.name
        profile_text = profile_file.read_text(encoding="utf-8")
        resume_file = profile_file.parent / "resume.txt"
        updated_at = timestamp_for(profile_file)
        db.execute(
            """
            INSERT INTO profiles (
                profile_name, resume_text, profile_json, profile_hash, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile_name) DO UPDATE SET
                resume_text = excluded.resume_text,
                profile_json = excluded.profile_json,
                profile_hash = excluded.profile_hash,
                updated_at = excluded.updated_at
            """,
            (
                profile_name,
                resume_file.read_text(encoding="utf-8") if resume_file.exists() else None,
                json_text(json.loads(profile_text)),
                hashlib.sha256(profile_text.encode("utf-8")).hexdigest(),
                updated_at,
            ),
        )


def import_profile_rankings(db: sqlite3.Connection, data_dir: Path) -> None:
    for ranked_file in sorted((data_dir / "ranked").glob("*.ranked.json")):
        job_uid = ranked_file.name.removesuffix(".ranked.json")
        ranked = read_json(ranked_file, {})
        rankings = ranked.get("profile_rankings", {})
        for profile_name, ranking in rankings.items():
            # Older ranked data can reference a profile whose source file is gone.
            db.execute(
                """
                INSERT OR IGNORE INTO profiles (
                    profile_name, profile_json, updated_at
                ) VALUES (?, '{}', ?)
                """,
                (profile_name, timestamp_for(ranked_file)),
            )
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
                (
                    job_uid,
                    profile_name,
                    ranking.get("overall_fit_score"),
                    json_text(ranking),
                    timestamp_for(ranked_file),
                ),
            )


def migrate(data_dir: Path, database_file: Path) -> dict[str, int]:
    apply_migrations(database_file)
    statuses = read_json(data_dir / "state" / "job_status.json", {})
    job_uids = discover_job_uids(data_dir, statuses)

    with connect(database_file) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            for job_uid in sorted(job_uids):
                import_job(db, data_dir, job_uid, statuses.get(job_uid, {}))
            import_queue_items(db, data_dir)
            import_profiles(db, data_dir)
            import_profile_rankings(db, data_dir)
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()

        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("jobs", "job_artifacts", "queue_items", "profiles", "profile_rankings")
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import JobRanker filesystem data into SQLite without changing runtime behavior."
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_FILE)
    args = parser.parse_args()

    counts = migrate(args.data_dir, args.database)
    print(f"Imported filesystem data into {args.database}")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    print("The API, worker, and report generator still use the existing filesystem data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
