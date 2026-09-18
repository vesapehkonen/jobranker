from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobInput:
    job_uid: str
    title: str
    text: str
    status: str


@dataclass(frozen=True)
class ProfileInput:
    profile_name: str
    text: str


def connect_read_only(database_file: Path | str) -> sqlite3.Connection:
    uri = Path(database_file).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _object(value: str | None) -> dict:
    if not value:
        return {}
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def load_matching_inputs(
    database_file: Path | str,
    *,
    status: str | None = None,
    profile_name: str | None = None,
) -> tuple[list[JobInput], list[ProfileInput]]:
    """Load only Python-produced job text and original resume text.

    This query intentionally cannot access structured_json, ranked_json, or
    profile_json, preventing paid-AI features from leaking into local matching.
    """
    with connect_read_only(database_file) as db:
        job_where = "AND j.application_status = ?" if status else ""
        job_parameters = (status,) if status else ()
        job_rows = db.execute(
            f"""
            SELECT j.job_uid, j.page_title, j.application_status, a.cleaned_json
            FROM jobs AS j
            JOIN job_artifacts AS a ON a.job_uid = j.job_uid
            WHERE a.cleaned_json IS NOT NULL
            {job_where}
            ORDER BY j.job_uid
            """,
            job_parameters,
        ).fetchall()
        profile_where = "profile_name = ?" if profile_name else "enabled = 1"
        profile_parameters = (profile_name,) if profile_name else ()
        profile_rows = db.execute(
            f"""
            SELECT profile_name, resume_text
            FROM profiles
            WHERE {profile_where} AND resume_text IS NOT NULL
            ORDER BY profile_name
            """,
            profile_parameters,
        ).fetchall()

    jobs = []
    for row in job_rows:
        cleaned = _object(row["cleaned_json"])
        text = str(cleaned.get("description_text") or "").strip()
        if text:
            jobs.append(JobInput(
                job_uid=row["job_uid"],
                title=str(row["page_title"] or cleaned.get("page_title") or ""),
                text=text,
                status=row["application_status"],
            ))
    profiles = [
        ProfileInput(row["profile_name"], str(row["resume_text"]).strip())
        for row in profile_rows if str(row["resume_text"]).strip()
    ]
    return jobs, profiles


def load_evaluation_references(database_file: Path | str) -> dict[tuple[str, str], float]:
    """Load AI scores separately, for evaluation only—not matcher features."""
    with connect_read_only(database_file) as db:
        rows = db.execute(
            """
            SELECT job_uid, profile_name, score
            FROM profile_rankings
            WHERE score IS NOT NULL
            """
        ).fetchall()
    return {(row["job_uid"], row["profile_name"]): float(row["score"]) for row in rows}
