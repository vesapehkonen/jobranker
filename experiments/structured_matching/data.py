from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from experiments.local_matching.data import connect_read_only


@dataclass(frozen=True)
class StructuredJobInput:
    job_uid: str
    title: str
    description: str
    ai_score: float | None


def load_inputs(
    database_file: Path | str,
    *,
    status: str | None = "experiment",
    profile_name: str = "backend",
) -> tuple[list[StructuredJobInput], dict]:
    with connect_read_only(database_file) as db:
        profile_row = db.execute(
            "SELECT profile_json FROM profiles WHERE profile_name = ?",
            (profile_name,),
        ).fetchone()
        if profile_row is None:
            raise ValueError(f"Profile not found: {profile_name}")
        status_clause = "WHERE j.application_status = ?" if status is not None else "WHERE 1 = 1"
        parameters = (profile_name, status) if status is not None else (profile_name,)
        rows = db.execute(
            f"""
            SELECT j.job_uid, j.page_title, a.cleaned_json, pr.score
            FROM jobs AS j
            JOIN job_artifacts AS a ON a.job_uid = j.job_uid
            LEFT JOIN profile_rankings AS pr
              ON pr.job_uid = j.job_uid AND pr.profile_name = ?
            {status_clause} AND a.cleaned_json IS NOT NULL
            ORDER BY j.created_at, j.job_uid
            """,
            parameters,
        ).fetchall()

    jobs = []
    for row in rows:
        cleaned = json.loads(row["cleaned_json"])
        description = str(cleaned.get("description_text") or "").strip()
        if description:
            jobs.append(StructuredJobInput(
                row["job_uid"], str(row["page_title"] or ""), description,
                float(row["score"]) if row["score"] is not None else None,
            ))
    return jobs, json.loads(profile_row["profile_json"])
