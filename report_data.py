import json
from datetime import datetime
from html import escape

from database import connect

STATUS_PRIORITY = {
    "new": 0, "interested": 1, "applied": 2, "recruiter_contact": 3,
    "interview": 4, "final_round": 5, "offer": 6, "skipped": 7,
    "rejected": 8, "withdrawn": 9, "archived": 10,
}


def decode_json(value: str | None) -> dict:
    if not value:
        return {}
    data = json.loads(value)
    return data if isinstance(data, dict) else {}


def parse_timestamp(value: str | None) -> float:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0


def html_list(items: list[str]) -> str:
    if not items:
        return "<p class='muted'>None listed</p>"
    return "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in items) + "</ul>"


def format_timestamp(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%b %d %H:%M")
    except (TypeError, ValueError):
        return value


def read_ranked_jobs(job_uid: str | None = None) -> list[dict]:
    where = "WHERE j.job_uid = ?" if job_uid is not None else ""
    parameters = (job_uid,) if job_uid is not None else ()
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT
                j.*,
                a.raw_json, a.cleaned_json, a.structured_json, a.ranked_json,
                q.status AS processing_status,
                q.phase AS processing_phase,
                q.error AS processing_error
            FROM jobs AS j
            LEFT JOIN job_artifacts AS a ON a.job_uid = j.job_uid
            LEFT JOIN queue_items AS q ON q.id = (
                SELECT q2.id FROM queue_items AS q2
                WHERE q2.job_uid = j.job_uid
                ORDER BY q2.id DESC LIMIT 1
            )
            {where}
            """,
            parameters,
        ).fetchall()

    jobs = []
    for row in rows:
        raw_job = decode_json(row["raw_json"])
        cleaned_job = decode_json(row["cleaned_json"])
        structured_job = decode_json(row["structured_json"])
        ranked_data = decode_json(row["ranked_json"])
        ranked_job = ranked_data.get("job", {})
        ranking = ranked_data.get("ranking", {})

        # Merge from least to most structured so pending/failed jobs retain
        # capture metadata while completed jobs use AI-extracted values.
        job = {**raw_job, **cleaned_job, **ranked_job, **structured_job}
        matched_strengths = ranking.get("matched_strengths", [])
        weak_areas = ranking.get("missing_or_weak_areas", [])
        interview_risk = ranking.get("interview_risk", [])
        requirements = job.get("requirements", [])
        preferred_requirements = job.get("preferred_requirements", [])
        technologies = job.get("technologies", [])
        benefits = job.get("benefits", [])
        created_at = row["created_at"] or ""
        status_updated_at = row["status_updated_at"] or row["updated_at"] or ""
        title = job.get("title") or job.get("page_title") or row["page_title"] or ""
        if "application_url" in raw_job:
            url = raw_job.get("application_url") or ""
        else:
            url = job.get("job_url") or job.get("url") or row["original_url"] or ""

        jobs.append({
            "job_uid": row["job_uid"],
            "file": f"{row['job_uid']}.ranked.json" if row["ranked_json"] else "",
            "status": row["application_status"],
            "notes": row["notes"],
            "status_updated_at": format_timestamp(status_updated_at),
            "score": ranking.get("overall_fit_score"),
            "recommendation": ranking.get("recommendation"),
            "company": job.get("company"),
            "title": title,
            "location": job.get("location"),
            "workplace_type": job.get("workplace_type"),
            "employment_type": job.get("employment_type"),
            "salary_range": job.get("salary_range"),
            "education_requirement": job.get("education_requirement"),
            "main_skill": job.get("main_skill"),
            "url": url,
            "summary": job.get("summary"),
            "short_summary": job.get("short_summary"),
            "description": job.get("description"),
            "matched_strengths": matched_strengths,
            "weak_areas": weak_areas,
            "interview_risk": interview_risk,
            "reasoning": ranking.get("reasoning") or "",
            "requirements": requirements,
            "preferred_requirements": preferred_requirements,
            "technologies": technologies,
            "benefits": benefits,
            "matched_strengths_html": html_list(matched_strengths),
            "weak_areas_html": html_list(weak_areas),
            "interview_risk_html": html_list(interview_risk),
            "requirements_html": html_list(requirements),
            "preferred_requirements_html": html_list(preferred_requirements),
            "technologies_html": html_list(technologies),
            "benefits_html": html_list(benefits),
            "external_job_id": job.get("job_id") or row["external_job_id"],
            "job_source": job.get("job_source") or row["source"],
            "recruiter_name": job.get("recruiter_name"),
            "recruiter_email": job.get("recruiter_email"),
            "cleaned_description_text": cleaned_job.get("description_text"),
            "created_at": format_timestamp(created_at),
            "created_at_ts": parse_timestamp(created_at),
            "recommended_profile": ranked_data.get("recommended_profile"),
            "profile_scores": ranked_data.get("profile_scores", {}),
            "dimension_scores": ranking.get("scores", {}),
            "processing_status": row["processing_status"] or "",
            "processing_phase": row["processing_phase"] or "",
            "processing_error": row["processing_error"] or "",
            "status_updated_at_raw": status_updated_at,
            "created_at_raw": created_at,
        })

    jobs.sort(key=lambda item: (
        STATUS_PRIORITY.get(item["status"], 99),
        -(item["created_at_ts"] or 0),
    ))
    return jobs


def read_job(job_uid: str) -> dict | None:
    """Return the report representation for one job."""
    return next(
        iter(read_ranked_jobs(job_uid)),
        None,
    )
