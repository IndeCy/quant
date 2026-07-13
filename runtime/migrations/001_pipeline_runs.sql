CREATE TABLE pipeline_runs (
    run_id TEXT NOT NULL PRIMARY KEY,
    pipeline_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    status TEXT NOT NULL,
    code_version TEXT NOT NULL DEFAULT '',
    data_version TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_pipeline_runs_lookup
ON pipeline_runs(pipeline_id, trade_date, started_at);

CREATE INDEX idx_pipeline_runs_status
ON pipeline_runs(status, started_at);
