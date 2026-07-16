CREATE TABLE strategy_commit_journal (
    commit_id TEXT NOT NULL PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    pipeline_run_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    last_step TEXT NOT NULL DEFAULT 'BEGIN',
    attempt_count INTEGER NOT NULL DEFAULT 1,
    code_version TEXT NOT NULL DEFAULT '',
    data_version TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT NOT NULL DEFAULT '',
    UNIQUE(strategy_id, trade_date)
);

CREATE INDEX idx_strategy_commit_status
ON strategy_commit_journal(status, updated_at);

CREATE INDEX idx_strategy_commit_pipeline_run
ON strategy_commit_journal(pipeline_run_id, strategy_id);

