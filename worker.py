import time
import traceback

from openai import OpenAI

from database import (
    claim_next_queue_item,
    complete_queue_item,
    fail_queue_item,
    initialize_database,
    load_enabled_profiles,
    save_job_artifact,
    update_queue_phase,
)
from extract_job_ai import DEFAULT_PROMPT_FILE, extract_job, read_prompt
from parse import parse_job
from rank_job_ai import rank_job

POLL_SECONDS = 2


def process_queue_item(item: dict) -> None:
    queue_id = item["id"]
    job_uid = item["job_uid"]
    raw = item.get("raw")
    if not isinstance(raw, dict):
        raise ValueError(f"Job {job_uid} has no raw JSON artifact")

    print(f"Processing job {job_uid}", flush=True)
    update_queue_phase(queue_id, "parse")
    cleaned = parse_job(raw)
    save_job_artifact(job_uid, "cleaned", cleaned)

    update_queue_phase(queue_id, "extract")
    client = OpenAI()
    structured = extract_job(
        client, cleaned, read_prompt(DEFAULT_PROMPT_FILE), job_uid=job_uid
    )
    save_job_artifact(job_uid, "structured", structured)

    update_queue_phase(queue_id, "rank")
    profiles = load_enabled_profiles()
    ranked = rank_job(client, structured, profiles, job_uid=job_uid)
    save_job_artifact(job_uid, "ranked", ranked)

    complete_queue_item(queue_id)
    print(f"Done job {job_uid}", flush=True)


def run_once() -> bool:
    item = claim_next_queue_item()
    if item is None:
        return False
    try:
        process_queue_item(item)
    except Exception as error:
        fail_queue_item(item["id"], str(error), traceback.format_exc())
        print(f"Failed job {item['job_uid']}: {error}", flush=True)
    return True


def main() -> None:
    initialize_database()
    print("Worker started", flush=True)
    print("Watching SQLite queue", flush=True)
    while True:
        if not run_once():
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
