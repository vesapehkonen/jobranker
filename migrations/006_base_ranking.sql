CREATE TABLE job_ai_cache (
    job_uid TEXT NOT NULL REFERENCES jobs(job_uid) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_uid, stage, input_hash)
);
CREATE TABLE base_rank_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid TEXT NOT NULL REFERENCES jobs(job_uid) ON DELETE CASCADE,
    queue_id INTEGER REFERENCES queue_items(id) ON DELETE SET NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('passed', 'filtered_out')),
    evaluation_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX base_rank_job_history ON base_rank_evaluations(job_uid, id);
