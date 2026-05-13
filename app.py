import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import subprocess
import sys
import os

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

RAW_DIR = Path("data/raw")
CLEANED_DIR = Path("data/cleaned")
STRUCTURED_DIR = Path("data/structured")
RANKED_DIR = Path("data/ranked")
REPORT_DIR = Path("data/reports")
STATE_DIR = Path("data/state")
QUEUE_DIR = Path("data/queue")

PENDING_DIR = QUEUE_DIR / "pending"
PROCESSING_DIR = QUEUE_DIR / "processing"
DONE_DIR = QUEUE_DIR / "done"
FAILED_DIR = QUEUE_DIR / "failed"

STATUS_FILE = STATE_DIR / "job_status.json"
REPORT_FILE = REPORT_DIR / "jobs.html"

API_TOKEN = os.getenv("API_TOKEN")

ALLOWED_STATUSES = {
    "new",
    "interested",
    "applied",
    "recruiter_contact",
    "interview",
    "final_round",
    "offer",
    "rejected",
    "withdrawn",
    "skipped",
    "archived",
}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    for directory in [
        RAW_DIR,
        CLEANED_DIR,
        STRUCTURED_DIR,
        RANKED_DIR,
        REPORT_DIR,
        STATE_DIR,
        PENDING_DIR,
        PROCESSING_DIR,
        DONE_DIR,
        FAILED_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def safe_slug(value: str | None) -> str:
    value = value or "job"
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:80] or "job"


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def build_job_uid(payload: dict[str, Any]) -> str:
    # Prefer URL because it is the best stable identifier before AI extraction.
    # Title is included as extra protection for portals with generic URLs.
    key = "|".join([
        normalize(payload.get("url")),
        normalize(payload.get("title")),
    ])

    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def load_statuses() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return {}

    return json.loads(STATUS_FILE.read_text(encoding="utf-8"))


def save_statuses(statuses: dict[str, Any]) -> None:
    STATUS_FILE.write_text(
        json.dumps(statuses, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def queue_file_for(job_uid: str, directory: Path) -> Path:
    return directory / f"{job_uid}.json"


def queue_item_exists(job_uid: str) -> bool:
    return any(
        queue_file_for(job_uid, directory).exists()
        for directory in [PENDING_DIR, PROCESSING_DIR, DONE_DIR]
    )


def ranked_file_exists(job_uid: str) -> bool:
    return (RANKED_DIR / f"{job_uid}.ranked.json").exists()


def create_queue_item(job_uid: str, raw_file: Path, payload: dict[str, Any]) -> Path:
    queue_file = queue_file_for(job_uid, PENDING_DIR)

    item = {
        "job_uid": job_uid,
        "status": "pending",
        "raw_file": str(raw_file),
        "created_at": utc_now(),
        "title": payload.get("title"),
        "url": payload.get("url"),
    }

    queue_file.write_text(
        json.dumps(item, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return queue_file


def get_existing_job_state(job_uid: str) -> str | None:
    if queue_file_for(job_uid, PENDING_DIR).exists():
        return "queued"

    if queue_file_for(job_uid, PROCESSING_DIR).exists():
        return "processing"

    if queue_file_for(job_uid, FAILED_DIR).exists():
        return "failed_existing"

    if ranked_file_exists(job_uid) or queue_file_for(job_uid, DONE_DIR).exists():
        return "already_processed"

    return None


def regenerate_report() -> None:
    result = subprocess.run(
        [sys.executable, "generate_report.py"],
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Status was saved, but report regeneration failed.",
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )


def verify_api_token(authorization: str | None = Header(default=None),) -> None:
    if not API_TOKEN:
        raise RuntimeError("API_TOKEN environment variable is not set")

    expected = f"Bearer {API_TOKEN}"
    print(f"authorization: {authorization}")
    print(f"expected: {expected}")
    if authorization != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API token",
        )
    

@app.post("/jobs/capture")
def capture_job(payload: dict[str, Any], _: None = Depends(verify_api_token)) -> JSONResponse:
    ensure_dirs()

    job_uid = build_job_uid(payload)
    raw_file = RAW_DIR / f"{job_uid}.raw.json"

    existing_state = get_existing_job_state(job_uid)

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

    raw_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    statuses = load_statuses()
    statuses[job_uid] = {
        **statuses.get(job_uid, {}),
        "status": statuses.get(job_uid, {}).get("status", "new"),
        "created_at": statuses.get(job_uid, {}).get("created_at", utc_now()),
        "updated_at": utc_now(),
        "title": payload.get("title"),
        "url": payload.get("url"),
        "notes": statuses.get(job_uid, {}).get("notes", ""),
    }
    save_statuses(statuses)

    queue_file = create_queue_item(job_uid, raw_file, payload)

    return JSONResponse({
        "status": "queued",
        "job_uid": job_uid,
        "raw_file": str(raw_file),
        "queue_file": str(queue_file),
        "message": "Job captured and queued for processing.",
        "report_url": "http://127.0.0.1:8000/report",
    })


@app.post("/jobs/{job_uid}/status")
def update_job_status(job_uid: str, payload: dict[str, Any], _: None = Depends(verify_api_token)) -> JSONResponse:
    ensure_dirs()

    status = payload.get("status")

    if status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    statuses = load_statuses()

    existing = statuses.get(job_uid, {})
    now = utc_now()

    existing["status"] = status
    existing["updated_at"] = now
    existing["status_updated_at"] = now

    if "created_at" not in existing:
        existing["created_at"] = now

    if "notes" not in existing:
        existing["notes"] = ""

    statuses[job_uid] = existing
    save_statuses(statuses)

    regenerate_report()

    return JSONResponse({
        "status": "ok",
        "job_uid": job_uid,
        "job_status": status,
        "report_regenerated": True,
    })


@app.post("/jobs/{job_uid}/notes")
def update_job_notes(job_uid: str, payload: dict[str, Any], _: None = Depends(verify_api_token)) -> JSONResponse:
    ensure_dirs()

    notes = payload.get("notes")

    if notes is None:
        raise HTTPException(status_code=400, detail="Missing notes")

    statuses = load_statuses()

    existing = statuses.get(job_uid, {})
    now = utc_now()

    existing["notes"] = str(notes)
    existing["updated_at"] = now

    if "created_at" not in existing:
        existing["created_at"] = now

    if "status" not in existing:
        existing["status"] = "new"

    statuses[job_uid] = existing
    save_statuses(statuses)

    return JSONResponse({
        "status": "ok",
        "job_uid": job_uid,
        "notes": existing["notes"],
    })


@app.get("/jobs/{job_uid}/queue")
def get_job_queue_status(job_uid: str, _: None = Depends(verify_api_token)) -> JSONResponse:
    ensure_dirs()

    for state, directory in [
        ("pending", PENDING_DIR),
        ("processing", PROCESSING_DIR),
        ("done", DONE_DIR),
        ("failed", FAILED_DIR),
    ]:
        queue_file = queue_file_for(job_uid, directory)

        if queue_file.exists():
            item = json.loads(queue_file.read_text(encoding="utf-8"))
            return JSONResponse({
                "status": state,
                "job_uid": job_uid,
                "queue_item": item,
            })

    if ranked_file_exists(job_uid):
        return JSONResponse({
            "status": "done",
            "job_uid": job_uid,
        })

    return JSONResponse({
        "status": "unknown",
        "job_uid": job_uid,
    })


@app.get("/queue")
def queue_summary( _: None = Depends(verify_api_token)) -> dict[str, int]:
    ensure_dirs()

    return {
        "pending": len(list(PENDING_DIR.glob("*.json"))),
        "processing": len(list(PROCESSING_DIR.glob("*.json"))),
        "done": len(list(DONE_DIR.glob("*.json"))),
        "failed": len(list(FAILED_DIR.glob("*.json"))),
    }


@app.get("/report")
def report() -> FileResponse:
    if not REPORT_FILE.exists():
        regenerate_report()
    if not REPORT_FILE.exists():
        raise HTTPException(status_code=404, detail="Report not found yet")

    return FileResponse(REPORT_FILE)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs/{job_uid}/retry")
def retry_job(job_uid: str, _: None = Depends(verify_api_token)) -> JSONResponse:
    ensure_dirs()

    failed_file = queue_file_for(job_uid, FAILED_DIR)

    if not failed_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No failed queue item found for {job_uid}",
        )

    pending_file = queue_file_for(job_uid, PENDING_DIR)

    if pending_file.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_uid} is already pending",
        )

    item = json.loads(failed_file.read_text(encoding="utf-8"))

    item["status"] = "pending"
    item["retried_at"] = utc_now()

    item.pop("error", None)
    item.pop("traceback", None)
    item.pop("failed_at", None)

    pending_file.write_text(
        json.dumps(item, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    failed_file.unlink()

    statuses = load_statuses()
    existing = statuses.get(job_uid, {})

    existing["processing_status"] = "pending"
    existing["queue_status"] = "pending"
    existing["processing_phase"] = "queued"
    existing["processing_updated_at"] = utc_now()

    existing.pop("processing_error", None)
    existing.pop("processing_failed_at", None)

    statuses[job_uid] = existing
    save_statuses(statuses)

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
        "mtime": int(REPORT_FILE.stat().st_mtime) if exists else 0
    }
