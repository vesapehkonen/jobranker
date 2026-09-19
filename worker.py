import time
import traceback

from openai import OpenAI

from database import (
    DEFAULT_DATABASE_FILE,
    save_local_filter_evaluation,
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
from job_matching.filtering import filter_description
from merge_resume_profiles import load_base_profile
from rank_job_ai import rank_job
from base_ranking import extraction_key, load_cached, save_cached, evaluate_base, save_base_evaluation

POLL_SECONDS = 2


def process_queue_item(item: dict, *, database_file=DEFAULT_DATABASE_FILE) -> None:
    queue_id = item["id"]
    job_uid = item["job_uid"]
    raw = item.get("raw")
    if not isinstance(raw, dict):
        raise ValueError(f"Job {job_uid} has no raw JSON artifact")

    print(f"Processing job {job_uid}", flush=True)
    update_queue_phase(queue_id, "parse", database_file=database_file)
    base = load_base_profile(database_file=database_file)
    if not base or not base.get("profile"):
        raise ValueError("Missing or stale base profile; run merge_resume_profiles.py before processing jobs")
    text = raw.get("text") or raw.get("raw_text") or ""
    cleaned = parse_job(raw) if text else {"description_text": "", "page_title": raw.get("title"), "url": raw.get("url")}
    save_job_artifact(job_uid, "cleaned", cleaned, database_file=database_file)

    update_queue_phase(queue_id, "local_filter", database_file=database_file)
    print(f"Local filtering job {job_uid}", flush=True)
    evaluation = filter_description(cleaned["description_text"], base)
    save_local_filter_evaluation(job_uid, queue_id, evaluation, database_file=database_file)
    if evaluation["outcome"] == "filtered_out":
        print(f"Filtered job {job_uid}: " + "; ".join(reason["message"] for reason in evaluation["reasons"]), flush=True)
        return

    print(f"Local filter passed job {job_uid}; continuing to AI extraction", flush=True)
    update_queue_phase(queue_id, "extract", database_file=database_file)
    client = OpenAI()
    prompt = read_prompt(DEFAULT_PROMPT_FILE)
    key = extraction_key(cleaned, prompt)
    structured = load_cached(job_uid, "extract", key, database_file=database_file)
    if structured is None:
        structured = extract_job(client, cleaned, prompt, job_uid=job_uid, database_file=database_file)
        if not isinstance(structured, dict) or not structured:
            raise ValueError("AI extraction returned an invalid job object")
        save_cached(job_uid, "extract", key, structured, database_file=database_file)
    else:
        print(f"Reusing AI extraction for job {job_uid}", flush=True)
    save_job_artifact(job_uid, "structured", structured, database_file=database_file)

    update_queue_phase(queue_id, "base_rank", database_file=database_file)
    base = load_base_profile(database_file=database_file)
    print(f"Ranking job {job_uid} against base profile", flush=True)
    base_evaluation = evaluate_base(client, structured, base, job_uid, database_file=database_file)
    save_base_evaluation(job_uid, queue_id, base_evaluation, database_file=database_file)
    print(base_evaluation["reason"], flush=True)
    if base_evaluation["outcome"] == "filtered_out":
        return

    update_queue_phase(queue_id, "rank", database_file=database_file)
    profiles = load_enabled_profiles(database_file=database_file)
    ranked = rank_job(client, structured, profiles, job_uid=job_uid)
    save_job_artifact(job_uid, "ranked", ranked, database_file=database_file)

    complete_queue_item(queue_id, database_file=database_file)
    print(f"Done job {job_uid}", flush=True)


def run_once(*, database_file=DEFAULT_DATABASE_FILE) -> bool:
    item = claim_next_queue_item(database_file=database_file)
    if item is None:
        return False
    try:
        process_queue_item(item, database_file=database_file)
    except Exception as error:
        fail_queue_item(item["id"], str(error), traceback.format_exc(), database_file=database_file)
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
