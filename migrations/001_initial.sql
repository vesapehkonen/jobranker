PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_uid             TEXT PRIMARY KEY,
    canonical_url       TEXT,
    original_url        TEXT,
    page_title          TEXT,
    source              TEXT,
    external_job_id     TEXT,
    application_status  TEXT NOT NULL DEFAULT 'new',
    notes               TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    status_updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS jobs_source_external_id
ON jobs(source, external_job_id)
WHERE source IS NOT NULL AND external_job_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS job_artifacts (
    job_uid               TEXT PRIMARY KEY
                          REFERENCES jobs(job_uid) ON DELETE CASCADE,
    raw_json              TEXT,
    cleaned_json          TEXT,
    structured_json       TEXT,
    ranked_json           TEXT,
    raw_updated_at        TEXT,
    cleaned_updated_at    TEXT,
    structured_updated_at TEXT,
    ranked_updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS queue_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid           TEXT NOT NULL
                      REFERENCES jobs(job_uid) ON DELETE CASCADE,
    legacy_key        TEXT UNIQUE,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    phase             TEXT NOT NULL DEFAULT 'queued',
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    available_at      TEXT NOT NULL,
    claimed_at        TEXT,
    lease_expires_at  TEXT,
    finished_at       TEXT,
    error             TEXT,
    traceback         TEXT,
    payload_json      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_queue_item_per_job
ON queue_items(job_uid)
WHERE status IN ('pending', 'processing');

CREATE INDEX IF NOT EXISTS queue_work_index
ON queue_items(status, available_at, created_at);

CREATE TABLE IF NOT EXISTS application_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid     TEXT NOT NULL
                REFERENCES jobs(job_uid) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    profile_name  TEXT PRIMARY KEY,
    resume_text   TEXT,
    profile_json  TEXT NOT NULL,
    profile_hash  TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_rankings (
    job_uid       TEXT NOT NULL
                  REFERENCES jobs(job_uid) ON DELETE CASCADE,
    profile_name  TEXT NOT NULL
                  REFERENCES profiles(profile_name) ON DELETE CASCADE,
    score         INTEGER,
    ranking_json  TEXT NOT NULL,
    model         TEXT,
    input_hash    TEXT,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (job_uid, profile_name)
);
