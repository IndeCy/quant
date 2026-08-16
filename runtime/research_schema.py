"""研究实验资产的 SQLite Schema。"""

from __future__ import annotations

import sqlite3


def init_research_schema(con: sqlite3.Connection) -> None:
    """初始化研究定义、运行、产物和去重复用审计。"""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS experiments (
            experiment_id TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            owner TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            hypothesis TEXT NOT NULL DEFAULT '',
            definition_fingerprint TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_runs (
            run_id TEXT NOT NULL PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            run_date TEXT NOT NULL,
            status TEXT NOT NULL,
            output_dir TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            message TEXT NOT NULL DEFAULT '',
            definition_fingerprint TEXT NOT NULL DEFAULT '',
            run_fingerprint TEXT NOT NULL DEFAULT '',
            data_as_of TEXT NOT NULL DEFAULT '',
            data_version TEXT NOT NULL DEFAULT '',
            outcome TEXT NOT NULL DEFAULT '',
            decision_reason TEXT NOT NULL DEFAULT '',
            reused_from_run_id TEXT NOT NULL DEFAULT '',
            reuse_count INTEGER NOT NULL DEFAULT 0,
            last_reused_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_artifacts (
            artifact_id TEXT NOT NULL PRIMARY KEY,
            run_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
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
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS research_attempt_reuse_events (
            event_id TEXT NOT NULL PRIMARY KEY,
            source_run_id TEXT NOT NULL,
            requested_experiment_id TEXT NOT NULL,
            run_fingerprint TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # 兼容已有系统状态库，增列保持幂等。
    _ensure_column(con, "experiments", "hypothesis", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiments", "definition_fingerprint", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiment_runs", "definition_fingerprint", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiment_runs", "run_fingerprint", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiment_runs", "data_as_of", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiment_runs", "data_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiment_runs", "outcome", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiment_runs", "decision_reason", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiment_runs", "reused_from_run_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "experiment_runs", "reuse_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(con, "experiment_runs", "last_reused_at", "TEXT NOT NULL DEFAULT ''")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_experiment_runs_exp "
        "ON experiment_runs(experiment_id, run_date)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_experiment_runs_fingerprint "
        "ON experiment_runs(run_fingerprint, status, created_at)"
    )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uk_experiment_runs_active_fingerprint "
        "ON experiment_runs(run_fingerprint) "
        "WHERE run_fingerprint <> '' AND status = 'RUNNING'"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_reuse_source "
        "ON research_attempt_reuse_events(source_run_id, created_at)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_experiment_artifacts_run "
        "ON experiment_artifacts(run_id)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_experiment_series_latest "
        "ON experiment_series_daily("
        "experiment_id, run_id, series_id, trade_date)"
    )


def _ensure_column(
    con: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {str(row[1]) for row in rows}:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
