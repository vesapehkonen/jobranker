import hashlib
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import (
    capture_job_record,
    initialize_database,
    latest_queue_item,
    list_job_summaries,
    job_count,
    queue_counts,
    report_version,
    retry_failed_queue_item,
    update_application_status,
    update_job_notes as update_notes_in_database,
)
from description_format import format_description
from report_data import read_job

API_TOKEN = os.getenv("API_TOKEN")
ALLOWED_STATUSES = {
    "new", "interested", "applied", "recruiter_contact", "interview",
    "final_round", "offer", "rejected", "withdrawn", "skipped", "archived",
}

@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def build_job_uid(payload: dict[str, Any]) -> str:
    key = "|".join([normalize(payload.get("url")), normalize(payload.get("title"))])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def verify_api_token(authorization: str | None = Header(default=None)) -> None:
    if not API_TOKEN:
        raise RuntimeError("API_TOKEN environment variable is not set")
    if authorization != f"Bearer {API_TOKEN}":
        print("Invalid or missing API token")
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


@app.post("/jobs/capture")
def capture_job(payload: dict[str, Any], _: None = Depends(verify_api_token)) -> JSONResponse:
    job_uid = build_job_uid(payload)
    existing_state, queue_id = capture_job_record(job_uid, payload)
    if existing_state:
        messages = {
            "queued": "Job is already queued.",
            "processing": "Job is already being processed.",
            "failed_existing": "Job was captured earlier, but processing failed. Retry from report.",
            "already_processed": "Job is already in the report.",
        }
        return JSONResponse(
            status_code=409,
            content={
                "status": existing_state,
                "job_uid": job_uid,
                "message": messages.get(existing_state, "Job already exists."),
                "report_url": "http://127.0.0.1:8000/report",
            },
        )
    return JSONResponse({
        "status": "queued",
        "job_uid": job_uid,
        "queue_id": queue_id,
        "message": "Job captured and queued for processing.",
        "report_url": "http://127.0.0.1:8000/report",
    })


@app.post("/jobs/{job_uid}/status")
def update_job_status(
    job_uid: str,
    payload: dict[str, Any],
    _: None = Depends(verify_api_token),
) -> JSONResponse:
    status = payload.get("status")
    if status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    update_application_status(job_uid, status)
    return JSONResponse({
        "status": "ok",
        "job_uid": job_uid,
        "job_status": status,
    })


@app.post("/jobs/{job_uid}/notes")
def update_job_notes(
    job_uid: str,
    payload: dict[str, Any],
    _: None = Depends(verify_api_token),
) -> JSONResponse:
    notes = payload.get("notes")
    if notes is None:
        raise HTTPException(status_code=400, detail="Missing notes")
    job = update_notes_in_database(job_uid, str(notes))
    return JSONResponse({
        "status": "ok",
        "job_uid": job_uid,
        "notes": job["notes"],
    })


@app.get("/jobs/{job_uid}/queue")
def get_job_queue_status(
    job_uid: str,
    _: None = Depends(verify_api_token),
) -> JSONResponse:
    item = latest_queue_item(job_uid)
    return JSONResponse({
        "status": item["status"] if item else "unknown",
        "job_uid": job_uid,
        "queue_item": item,
    })


@app.get("/queue")
def queue_summary(_: None = Depends(verify_api_token)) -> dict[str, int]:
    return queue_counts()


@app.get("/jobs")
def get_jobs(
    search: str = "",
    status: str = "new",
    sort: str = "newest",
    minimum_score: int | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    if status not in ALLOWED_STATUSES | {"all"}:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if sort not in {
        "newest", "oldest", "score_desc", "score_asc",
        "updated", "company", "title",
    }:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")
    if minimum_score is not None and not 0 <= minimum_score <= 100:
        raise HTTPException(status_code=400, detail="minimum_score must be 0-100")
    return list_job_summaries(
        search=search, status=status, sort=sort,
        minimum_score=minimum_score, page=page, page_size=page_size,
    )


@app.get("/jobs/{job_uid}")
def get_job_detail(
    job_uid: str,
) -> dict[str, Any]:
    job = read_job(job_uid)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_uid}")
    return {
        key: value for key, value in job.items()
        if not key.endswith("_html")
    }


@app.get("/jobs/{job_uid}/description")
def saved_job_description(request: Request, job_uid: str):
    job = read_job(job_uid)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_uid}")
    return templates.TemplateResponse(
        request=request,
        name="job_description.html",
        context={
            "job": job,
            "description_blocks": format_description(
                job.get("cleaned_description_text") or job.get("description")
            ),
        },
    )


@app.get("/report")
def report(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="jobs_report.html",
        context={
            "total_jobs": job_count(),
            "report_version": report_version(),
            "api_token": API_TOKEN or "",
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs/{job_uid}/retry")
def retry_job(job_uid: str, _: None = Depends(verify_api_token)) -> JSONResponse:
    result = retry_failed_queue_item(job_uid)
    if result == "not_found":
        raise HTTPException(status_code=404, detail=f"No failed queue item found for {job_uid}")
    if result == "active":
        raise HTTPException(status_code=409, detail=f"Job {job_uid} is already active")
    return JSONResponse({
        "status": "queued",
        "job_uid": job_uid,
        "message": "Job requeued for processing.",
    })


@app.get("/report/status")
def report_status() -> dict[str, str | bool | int]:
    return {
        "exists": True,
        "version": report_version(),
        "total_jobs": job_count(),
    }
