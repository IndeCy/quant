CREATE TABLE IF NOT EXISTS paper_execution_sla_daily (
    trade_date TEXT NOT NULL PRIMARY KEY,
    status TEXT NOT NULL,
    run_status TEXT NOT NULL DEFAULT '',
    due_orders INTEGER NOT NULL DEFAULT 0,
    filled_orders INTEGER NOT NULL DEFAULT 0,
    rejected_orders INTEGER NOT NULL DEFAULT 0,
    cancelled_orders INTEGER NOT NULL DEFAULT 0,
    pending_orders INTEGER NOT NULL DEFAULT 0,
    late_orders INTEGER NOT NULL DEFAULT 0,
    issues_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_execution_sla_status_date
ON paper_execution_sla_daily(status, trade_date);
