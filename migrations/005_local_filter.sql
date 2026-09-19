CREATE TABLE local_filter_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid TEXT NOT NULL REFERENCES jobs(job_uid) ON DELETE CASCADE,
    queue_id INTEGER REFERENCES queue_items(id) ON DELETE SET NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('passed', 'filtered_out')),
    evaluation_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX local_filter_job_history ON local_filter_evaluations(job_uid, id);
