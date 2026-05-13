import csv
import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
import time
import os

from jinja2 import Environment, FileSystemLoader, select_autoescape


RAW_DIR = Path("data/raw")
STRUCTURED_DIR = Path("data/structured")
CLEANED_DIR = Path("data/cleaned")
RANKED_DIR = Path("data/ranked")
REPORT_DIR = Path("data/reports")
STATUS_FILE = Path("data/state/job_status.json")
TEMPLATE_DIR = Path("templates")

CSV_FILE = REPORT_DIR / "jobs.csv"
HTML_FILE = REPORT_DIR / "jobs.html"

STATUS_PRIORITY = {
    "new": 0,
    "interested": 1,
    "applied": 2,
    "recruiter_contact": 3,
    "interview": 4,
    "final_round": 5,
    "offer": 6,
    "skipped": 7,
    "rejected": 8,
    "withdrawn": 9,
    "archived": 10,
}


def read_json_if_exists(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    return json.loads(path.read_text(encoding="utf-8"))


def parse_timestamp(value: str | None) -> float:
    if not value:
        return 0

    try:
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return 0


def load_statuses() -> dict:
    return read_json_if_exists(STATUS_FILE, {})


def html_list(items: list[str]) -> str:
    if not items:
        return "<p class='muted'>None listed</p>"

    return "<ul>" + "".join(
        f"<li>{escape(str(item))}</li>" for item in items
    ) + "</ul>"


def format_timestamp(value: str | None) -> str:
    if not value:
        return ""

    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%b %d %H:%M")
    except Exception:
        return value


def get_all_job_uids(statuses: dict) -> list[str]:
    ranked_uids = {
        file.name.replace(".ranked.json", "")
        for file in RANKED_DIR.glob("*.ranked.json")
    }

    status_uids = set(statuses.keys())

    return sorted(ranked_uids | status_uids)


def read_ranked_jobs() -> list[dict]:
    jobs = []
    statuses = load_statuses()

    for job_uid in get_all_job_uids(statuses):
        ranked_file = RANKED_DIR / f"{job_uid}.ranked.json"
        structured_file = STRUCTURED_DIR / f"{job_uid}.structured.json"
        cleaned_file = CLEANED_DIR / f"{job_uid}.cleaned.json"
        raw_file = RAW_DIR / f"{job_uid}.raw.json"

        ranked_data = read_json_if_exists(ranked_file, {})
        structured_job = read_json_if_exists(structured_file, {})
        cleaned_job = read_json_if_exists(cleaned_file, {})
        raw_job = read_json_if_exists(raw_file, {})

        status_data = statuses.get(job_uid, {})

        created_at = status_data.get("created_at") or ""
        created_at_ts = parse_timestamp(created_at)

        fallback_file = ranked_file if ranked_file.exists() else raw_file
        if not created_at_ts and fallback_file.exists():
            created_at_ts = fallback_file.stat().st_mtime
            created_at = datetime.fromtimestamp(created_at_ts).isoformat()

        job_status = status_data.get("status", "new")
        status_updated_at = (
            status_data.get("status_updated_at")
            or status_data.get("updated_at")
            or ""
        )

        ranked_job = ranked_data.get("job", {})
        ranking = ranked_data.get("ranking", {})

        # Merge from least structured to most structured.
        # This allows failed jobs to still show title/url from raw/status data.
        job = {
            **raw_job,
            **cleaned_job,
            **ranked_job,
            **structured_job,
        }

        matched_strengths = ranking.get("matched_strengths", [])
        weak_areas = ranking.get("missing_or_weak_areas", [])
        interview_risk = ranking.get("interview_risk", [])

        requirements = job.get("requirements", [])
        preferred_requirements = job.get("preferred_requirements", [])
        technologies = job.get("technologies", [])
        benefits = job.get("benefits", [])

        processing_status = status_data.get("processing_status", "")
        processing_phase = status_data.get("processing_phase", "")
        processing_error = status_data.get("processing_error", "")

        title = (
            job.get("title")
            or job.get("page_title")
            or status_data.get("title")
            or ""
        )

        url = (
            job.get("job_url")
            or job.get("url")
            or status_data.get("url")
            or "#"
        )

        jobs.append({
            "job_uid": job_uid,
            "file": ranked_file.name if ranked_file.exists() else "",
            "status": job_status,
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

            "external_job_id": job.get("job_id"),
            "job_source": job.get("job_source"),
            "cleaned_description_text": cleaned_job.get("description_text"),

            "created_at": format_timestamp(created_at),
            "created_at_ts": created_at_ts,

            "recommended_profile": ranked_data.get("recommended_profile"),
            "profile_scores": ranked_data.get("profile_scores", {}),

            "processing_status": processing_status,
            "processing_phase": processing_phase,
            "processing_error": processing_error,

            "status_updated_at_raw": status_updated_at,
            "created_at_raw": created_at,
        })

    jobs.sort(
        key=lambda x: (
            STATUS_PRIORITY.get(x["status"], 99),
            -(x["created_at_ts"] or 0),
        )
    )

    return jobs


def write_csv(jobs: list[dict]) -> None:
    if not jobs:
        print("No jobs found, no CSV file created.")
        return

    csv_jobs = []

    for job in jobs:
        csv_job = {
            key: value
            for key, value in job.items()
            if not key.endswith("_html")
        }

        for key in [
            "matched_strengths",
            "weak_areas",
            "interview_risk",
            "requirements",
            "preferred_requirements",
            "technologies",
            "benefits",
        ]:
            value = csv_job.get(key, [])
            csv_job[key] = "; ".join(value) if isinstance(value, list) else value

        csv_jobs.append(csv_job)

    with CSV_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_jobs[0].keys()))
        writer.writeheader()
        writer.writerows(csv_jobs)

    print(f"Saved {CSV_FILE}")



def write_html(jobs: list[dict]) -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )

    template = env.get_template("jobs_report.html")

    report_generated_at = int(time.time())
    
    html = template.render(
        jobs=jobs,
        total_jobs=len(jobs),
        report_mtime=report_generated_at,
         api_token=os.getenv("API_TOKEN", ""),
    )
    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"Saved {HTML_FILE}")


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    jobs = read_ranked_jobs()

    #if not jobs:
    #    print("No jobs found")
    #    return

    write_csv(jobs)
    write_html(jobs)


if __name__ == "__main__":
    main()
