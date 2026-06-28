"""系统运行状态库建表语句。"""

from __future__ import annotations

import sqlite3


def init_system_schema(con: sqlite3.Connection) -> None:
    """初始化本地运行状态库表结构。"""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_runs (
            strategy_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            status TEXT NOT NULL,
            run_dir TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (strategy_id, trade_date)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS report_index (
            report_id TEXT NOT NULL PRIMARY KEY,
            report_type TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            title TEXT NOT NULL,
            file_path TEXT NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_run_steps (
            strategy_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            step_name TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            artifact_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (strategy_id, trade_date, step_name)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_registry (
            factor_id TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            source TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_registry (
            strategy_id TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            strategy_type TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_factor_link (
            strategy_id TEXT NOT NULL,
            factor_id TEXT NOT NULL,
            weight REAL NOT NULL,
            transform TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (strategy_id, factor_id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_drafts (
            draft_id TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_draft_factors (
            draft_id TEXT NOT NULL,
            factor_id TEXT NOT NULL,
            weight REAL NOT NULL,
            transform TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (draft_id, factor_id)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_report_strategy_date ON report_index(strategy_id, trade_date)")
