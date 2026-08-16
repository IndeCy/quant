CREATE TABLE IF NOT EXISTS research_attempt_reuse_events (
    event_id TEXT NOT NULL PRIMARY KEY,
    source_run_id TEXT NOT NULL,
    requested_experiment_id TEXT NOT NULL,
    run_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_research_reuse_source
ON research_attempt_reuse_events(source_run_id, created_at);
