CREATE TABLE IF NOT EXISTS experiment_series_daily (
    run_id TEXT NOT NULL,
    experiment_id TEXT NOT NULL,
    series_id TEXT NOT NULL,
    series_name TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    nav REAL NOT NULL,
    adjust_policy TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, series_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_experiment_series_latest
ON experiment_series_daily(experiment_id, run_id, series_id, trade_date);
