"""AI base-profile gate and reusable job extraction results."""
import hashlib
import json

from config import JOB_EXTRACT_MODEL, JOB_RANK_MODEL
from database import DEFAULT_DATABASE_FILE, connect, utc_now
from extract_job_ai import SCHEMA as EXTRACTION_SCHEMA
from rank_job_ai import SCHEMA as RANKING_SCHEMA, WEIGHTS, rank_profile

BASE_SCORE_THRESHOLD = 75
RANKING_VERSION = 1
EXTRACTION_VERSION = 1


def input_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def extraction_key(cleaned, prompt):
    return input_hash([EXTRACTION_VERSION, JOB_EXTRACT_MODEL, EXTRACTION_SCHEMA, prompt, cleaned])


def load_cached(job_uid, stage, key, *, database_file=DEFAULT_DATABASE_FILE):
    with connect(database_file) as db:
        row = db.execute("SELECT response_json FROM job_ai_cache WHERE job_uid=? AND stage=? AND input_hash=?",
                         (job_uid, stage, key)).fetchone()
    return json.loads(row[0]) if row else None


def save_cached(job_uid, stage, key, value, *, database_file=DEFAULT_DATABASE_FILE):
    with connect(database_file) as db:
        db.execute("INSERT OR REPLACE INTO job_ai_cache VALUES (?, ?, ?, ?, ?)",
                   (job_uid, stage, key, json.dumps(value), utc_now()))


def validate_ranking(ranking):
    if not isinstance(ranking, dict):
        raise ValueError("Base ranking must be an object")
    for field in ("overall_fit_score",):
        score = ranking.get(field)
        if type(score) is not int or not 0 <= score <= 100:
            raise ValueError("Base ranking score must be an integer between 0 and 100")
    if not isinstance(ranking.get("reasoning"), str) or not ranking["reasoning"].strip():
        raise ValueError("Base ranking must include an explanation")


def evaluate_base(client, structured, base, job_uid, *, database_file=DEFAULT_DATABASE_FILE):
    if not base or base.get("status") != "ready" or not base.get("profile"):
        raise ValueError("A current base profile is required for AI ranking")
    key = input_hash([RANKING_VERSION, JOB_RANK_MODEL, RANKING_SCHEMA, WEIGHTS, structured,
                      base["profile"], base["sources"], base["merged_at"]])
    ranking = load_cached(job_uid, "base_rank", key, database_file=database_file)
    cached = ranking is not None
    if not cached:
        ranking = rank_profile(client, "merged_base", base["profile"], structured,
                               job_uid=job_uid, operation="base_rank", database_file=database_file)
    validate_ranking(ranking)
    score = ranking["overall_fit_score"]
    return {
        "outcome": "filtered_out" if score < BASE_SCORE_THRESHOLD else "passed",
        "score": score, "threshold": BASE_SCORE_THRESHOLD, "ranking": ranking,
        "reason": f"Base profile score {score} is below {BASE_SCORE_THRESHOLD}." if score < BASE_SCORE_THRESHOLD
                  else f"Base profile score {score} meets the {BASE_SCORE_THRESHOLD} threshold.",
        "base_sources": base["sources"], "base_merged_at": base["merged_at"],
        "base_profile_hash": input_hash(base["profile"]), "structured_hash": input_hash(structured),
        "model": JOB_RANK_MODEL, "ranking_version": RANKING_VERSION,
        "input_hash": key, "cached": cached,
    }


def save_base_evaluation(job_uid, queue_id, evaluation, *, database_file=DEFAULT_DATABASE_FILE):
    now = utc_now()
    with connect(database_file) as db:
        db.execute("BEGIN IMMEDIATE")
        base = db.execute("SELECT * FROM base_profile WHERE id=1").fetchone()
        if (not base or base["status"] != "ready" or base["merged_at"] != evaluation["base_merged_at"]
                or json.loads(base["sources_json"]) != evaluation["base_sources"]
                or input_hash(json.loads(base["profile_json"])) != evaluation["base_profile_hash"]):
            raise RuntimeError("Base profile changed during AI ranking; retry the job")
        queue = db.execute("SELECT * FROM queue_items WHERE id=?", (queue_id,)).fetchone()
        if not queue or queue["status"] != "processing" or queue["job_uid"] != job_uid:
            raise RuntimeError("Queue item is not processing this job")
        db.execute("INSERT INTO base_rank_evaluations (job_uid, queue_id, outcome, evaluation_json, created_at) VALUES (?, ?, ?, ?, ?)",
                   (job_uid, queue_id, evaluation["outcome"], json.dumps(evaluation), now))
        db.execute("INSERT OR REPLACE INTO job_ai_cache VALUES (?, 'base_rank', ?, ?, ?)",
                   (job_uid, evaluation["input_hash"], json.dumps(evaluation["ranking"]), now))
        if evaluation["outcome"] == "filtered_out":
            db.execute("UPDATE queue_items SET status='done', phase='base_filtered', finished_at=?, lease_expires_at=NULL, updated_at=? WHERE id=?",
                       (now, now, queue_id))
