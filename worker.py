import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


QUEUE_DIR = Path("data/queue")
PENDING_DIR = QUEUE_DIR / "pending"
PROCESSING_DIR = QUEUE_DIR / "processing"
DONE_DIR = QUEUE_DIR / "done"
FAILED_DIR = QUEUE_DIR / "failed"

RAW_DIR = Path("data/raw")
CLEANED_DIR = Path("data/cleaned")
STRUCTURED_DIR = Path("data/structured")
RANKED_DIR = Path("data/ranked")
REPORT_DIR = Path("data/reports")
STATE_DIR = Path("data/state")
STATUS_FILE = STATE_DIR / "job_status.json"

POLL_SECONDS = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    for directory in [
        PENDING_DIR,
        PROCESSING_DIR,
        DONE_DIR,
        FAILED_DIR,
        RAW_DIR,
        CLEANED_DIR,
        STRUCTURED_DIR,
        RANKED_DIR,
        REPORT_DIR,
        STATE_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def run(command: list[str]) -> None:
    print(f"Running: {' '.join(command)}", flush=True)

    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout, flush=True)

    if result.stderr:
        print(result.stderr, flush=True)

    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"Command: {' '.join(command)}\n"
            f"Exit code: {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_queue_item(path: Path) -> dict[str, Any]:
    return load_json_file(path, {})


def save_queue_item(path: Path, item: dict[str, Any]) -> None:
    write_json_file(path, item)


def load_statuses() -> dict[str, Any]:
    return load_json_file(STATUS_FILE, {})


def save_statuses(statuses: dict[str, Any]) -> None:
    write_json_file(STATUS_FILE, statuses)


def update_processing_status(
    job_uid: str,
    processing_status: str,
    *,
    queue_status: str | None = None,
    error: str | None = None,
    phase: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    statuses = load_statuses()
    existing = statuses.get(job_uid, {})

    now = utc_now()

    existing["processing_status"] = processing_status
    existing["processing_updated_at"] = now
    existing["updated_at"] = now

    if queue_status:
        existing["queue_status"] = queue_status

    if phase:
        existing["processing_phase"] = phase

    if processing_status == "processing":
        existing["processing_started_at"] = existing.get("processing_started_at", now)
        existing.pop("processing_error", None)
        existing.pop("processing_failed_at", None)

    if processing_status == "done":
        existing["processing_finished_at"] = now
        existing.pop("processing_error", None)
        existing.pop("processing_failed_at", None)

    if processing_status == "failed":
        existing["processing_failed_at"] = now
        existing["processing_error"] = error or "Unknown processing error"

    if "created_at" not in existing:
        existing["created_at"] = now

    if "status" not in existing:
        existing["status"] = "new"

    if "notes" not in existing:
        existing["notes"] = ""

    if extra:
        existing.update({k: v for k, v in extra.items() if v is not None})

    statuses[job_uid] = existing
    save_statuses(statuses)


def move_queue_file(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name

    if dst.exists():
        dst.unlink()

    shutil.move(str(src), str(dst))
    return dst


def oldest_pending_file() -> Path | None:
    pending = sorted(
        PENDING_DIR.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
    )

    if not pending:
        return None

    return pending[0]


def set_queue_phase(queue_file: Path, item: dict[str, Any], phase: str) -> None:
    item["processing_phase"] = phase
    item["updated_at"] = utc_now()
    save_queue_item(queue_file, item)


def process_queue_item(queue_file: Path) -> None:
    processing_file = move_queue_file(queue_file, PROCESSING_DIR)
    item = load_queue_item(processing_file)

    job_uid = item.get("job_uid")

    if not job_uid:
        raise ValueError(f"Queue item missing job_uid: {processing_file}")

    raw_file = Path(item.get("raw_file") or RAW_DIR / f"{job_uid}.raw.json")
    cleaned_file = CLEANED_DIR / f"{job_uid}.cleaned.json"
    structured_file = STRUCTURED_DIR / f"{job_uid}.structured.json"
    ranked_file = RANKED_DIR / f"{job_uid}.ranked.json"

    print(f"Processing job {job_uid}", flush=True)

    item["status"] = "processing"
    item["started_at"] = utc_now()
    set_queue_phase(processing_file, item, "started")

    update_processing_status(
        job_uid,
        "processing",
        queue_status="processing",
        phase="started",
        extra={
            "title": item.get("title"),
            "url": item.get("url"),
        },
    )

    if not raw_file.exists():
        raise FileNotFoundError(f"Missing raw file: {raw_file}")

    set_queue_phase(processing_file, item, "parse")
    update_processing_status(job_uid, "processing", queue_status="processing", phase="parse")
    run([
        sys.executable,
        "parse.py",
        str(raw_file),
        str(CLEANED_DIR),
    ])

    if not cleaned_file.exists():
        raise FileNotFoundError(f"Expected cleaned file was not created: {cleaned_file}")

    set_queue_phase(processing_file, item, "extract")
    update_processing_status(job_uid, "processing", queue_status="processing", phase="extract")
    run([
        sys.executable,
        "extract_job_ai.py",
        str(cleaned_file),
        str(STRUCTURED_DIR),
    ])

    if not structured_file.exists():
        raise FileNotFoundError(f"Expected structured file was not created: {structured_file}")

    set_queue_phase(processing_file, item, "rank")
    update_processing_status(job_uid, "processing", queue_status="processing", phase="rank")
    run([
        sys.executable,
        "rank_job_ai.py",
        str(structured_file),
        str(RANKED_DIR),
    ])

    if not ranked_file.exists():
        raise FileNotFoundError(f"Expected ranked file was not created: {ranked_file}")

    item["status"] = "done"
    item["finished_at"] = utc_now()
    item["cleaned_file"] = str(cleaned_file)
    item["structured_file"] = str(structured_file)
    item["ranked_file"] = str(ranked_file)

    save_queue_item(processing_file, item)

    update_processing_status(
        job_uid,
        "done",
        queue_status="done",
        phase="done",
        extra={
            "cleaned_file": str(cleaned_file),
            "structured_file": str(structured_file),
            "ranked_file": str(ranked_file),
        },
    )

    run([
        sys.executable,
        "generate_report.py",
    ])

    done_file = move_queue_file(processing_file, DONE_DIR)

    print(f"Done job {job_uid}: {done_file}", flush=True)


def fail_queue_item(queue_file: Path, error: BaseException) -> None:
    try:
        item = load_queue_item(queue_file)
    except Exception:
        item = {}

    job_uid = item.get("job_uid")
    error_text = str(error)

    item["status"] = "failed"
    item["failed_at"] = utc_now()
    item["error"] = error_text
    item["traceback"] = traceback.format_exc()

    save_queue_item(queue_file, item)
    failed_file = move_queue_file(queue_file, FAILED_DIR)

    if job_uid:
        update_processing_status(
            job_uid,
            "failed",
            queue_status="failed",
            phase=item.get("processing_phase") or "failed",
            error=error_text,
            extra={
                "failed_queue_file": str(failed_file),
            },
        )

    print(f"Failed job moved to {failed_file}", flush=True)
    print(f"Error: {error}", flush=True)


def run_once() -> bool:
    queue_file = oldest_pending_file()

    if queue_file is None:
        return False

    try:
        process_queue_item(queue_file)
    except Exception as error:
        processing_file = PROCESSING_DIR / queue_file.name

        if processing_file.exists():
            fail_queue_item(processing_file, error)
        elif queue_file.exists():
            fail_queue_item(queue_file, error)
        else:
            print(f"Failed job, but queue file disappeared: {queue_file}", flush=True)
            print(f"Error: {error}", flush=True)

    return True


def main() -> None:
    ensure_dirs()

    print("Worker started", flush=True)
    print(f"Watching {PENDING_DIR}", flush=True)

    while True:
        did_work = run_once()

        if not did_work:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
