CREATE TABLE strategy_risk_policy_events (
    event_id TEXT NOT NULL PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    action TEXT NOT NULL,
    max_exposure REAL NOT NULL DEFAULT 1,
    source_ack_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX uk_strategy_risk_policy_source
ON strategy_risk_policy_events(source_ack_id)
WHERE source_ack_id <> '';

CREATE INDEX idx_strategy_risk_policy_lookup
ON strategy_risk_policy_events(strategy_id, effective_date, created_at);
