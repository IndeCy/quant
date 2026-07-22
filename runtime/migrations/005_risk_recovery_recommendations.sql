CREATE TABLE strategy_risk_recovery_recommendations (
    recommendation_id TEXT NOT NULL PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    policy_effective_date TEXT NOT NULL,
    current_cap REAL NOT NULL DEFAULT 1,
    recommended_cap REAL NOT NULL DEFAULT 1,
    recommendation_action TEXT NOT NULL DEFAULT 'INCREASE',
    status TEXT NOT NULL DEFAULT 'PENDING',
    stable_days_observed INTEGER NOT NULL DEFAULT 0,
    stable_days_required INTEGER NOT NULL DEFAULT 3,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL DEFAULT '',
    execution_status TEXT NOT NULL DEFAULT '',
    execution_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_risk_recovery_status
ON strategy_risk_recovery_recommendations(status, trade_date);

CREATE INDEX idx_risk_recovery_strategy
ON strategy_risk_recovery_recommendations(strategy_id, trade_date);
