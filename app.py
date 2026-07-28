import hashlib
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from database import (
    capture_job_record,
    latest_queue_item,
    queue_counts,
    retry_failed_queue_item,
    update_application_status,
    update_job_notes as update_notes_in_database,
)
from generate_report import main as generate_report

REPORT_FILE = Path("data/reports/jobs.html")
API_TOKEN = os.getenv("API_TOKEN")
ALLOWED_STATUSES = {
    "new", "interested", "applied", "recruiter_contact", "interview",
    "final_round", "offer", "rejected", "withdrawn", "skipped", "archived",
}

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def build_job_uid(payload: dict[str, Any]) -> str:
    key = "|".join([normalize(payload.get("url")), normalize(payload.get("title"))])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def regenerate_report() -> None:
    try:
        generate_report()
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Database update succeeded, but report regeneration failed: {error}",
        ) from error


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
    regenerate_report()
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
    regenerate_report()
    return JSONResponse({
        "status": "ok",
        "job_uid": job_uid,
        "job_status": status,
        "report_regenerated": True,
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
    regenerate_report()
    return JSONResponse({
        "status": "ok",
        "job_uid": job_uid,
        "notes": job["notes"],
        "report_regenerated": True,
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


@app.get("/report")
def report() -> FileResponse:
    if not REPORT_FILE.exists():
        regenerate_report()
    return FileResponse(REPORT_FILE)


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
    regenerate_report()
    return JSONResponse({
        "status": "queued",
        "job_uid": job_uid,
        "message": "Job requeued for processing.",
    })


@app.get("/report/status")
def report_status() -> dict[str, float | bool]:
    exists = REPORT_FILE.exists()
    return {
        "exists": exists,
        "mtime": int(REPORT_FILE.stat().st_mtime) if exists else 0,
    }
