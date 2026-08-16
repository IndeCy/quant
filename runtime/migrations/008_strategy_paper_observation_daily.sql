CREATE TABLE IF NOT EXISTS strategy_paper_observation_daily (
    strategy_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    status TEXT NOT NULL,
    strategy_run_status TEXT NOT NULL DEFAULT '',
    execution_run_status TEXT NOT NULL DEFAULT '',
    due_orders INTEGER NOT NULL DEFAULT 0,
    filled_orders INTEGER NOT NULL DEFAULT 0,
    rejected_orders INTEGER NOT NULL DEFAULT 0,
    cancelled_orders INTEGER NOT NULL DEFAULT 0,
    pending_orders INTEGER NOT NULL DEFAULT 0,
    late_orders INTEGER NOT NULL DEFAULT 0,
    issues_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (strategy_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_strategy_paper_observation_status_date
ON strategy_paper_observation_daily(strategy_id, status, trade_date);
