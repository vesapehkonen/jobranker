CREATE TABLE IF NOT EXISTS ai_costs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    provider                 TEXT NOT NULL,
    operation                TEXT NOT NULL,
    model                    TEXT NOT NULL,
    response_id              TEXT,
    job_uid                  TEXT
                             REFERENCES jobs(job_uid) ON DELETE SET NULL,
    profile_name             TEXT,
    input_tokens             INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens      INTEGER NOT NULL DEFAULT 0,
    output_tokens            INTEGER NOT NULL DEFAULT 0,
    reasoning_output_tokens  INTEGER NOT NULL DEFAULT 0,
    total_tokens             INTEGER NOT NULL DEFAULT 0,
    input_cost_usd           REAL,
    cached_input_cost_usd    REAL,
    output_cost_usd          REAL,
    total_cost_usd           REAL,
    pricing_input_per_million        REAL,
    pricing_cached_per_million       REAL,
    pricing_output_per_million       REAL,
    created_at               TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ai_costs_provider_response
ON ai_costs(provider, response_id)
WHERE response_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ai_costs_created_at
ON ai_costs(created_at);

CREATE INDEX IF NOT EXISTS ai_costs_job_uid
ON ai_costs(job_uid);
