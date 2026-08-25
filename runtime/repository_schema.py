"""系统运行状态库建表语句。"""

from __future__ import annotations

import sqlite3

from runtime.research_schema import init_research_schema


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
        CREATE TABLE IF NOT EXISTS factor_contracts (
            factor_id TEXT NOT NULL PRIMARY KEY,
            version TEXT NOT NULL DEFAULT 'v1',
            status TEXT NOT NULL DEFAULT 'draft',
            frequency TEXT NOT NULL DEFAULT '',
            value_type TEXT NOT NULL DEFAULT '',
            as_of_policy TEXT NOT NULL DEFAULT '',
            as_of_field TEXT NOT NULL DEFAULT '',
            effective_date_field TEXT NOT NULL DEFAULT '',
            lag_days INTEGER NOT NULL DEFAULT 0,
            input_datasets_json TEXT NOT NULL DEFAULT '[]',
            input_fields_json TEXT NOT NULL DEFAULT '[]',
            output_fields_json TEXT NOT NULL DEFAULT '[]',
            dependencies_json TEXT NOT NULL DEFAULT '[]',
            validation_json TEXT NOT NULL DEFAULT '{}',
            owner TEXT NOT NULL DEFAULT '',
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
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_ideas (
            idea_id TEXT NOT NULL PRIMARY KEY,
            title TEXT NOT NULL,
            raw_description TEXT NOT NULL,
            source TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            required_data_json TEXT NOT NULL DEFAULT '[]',
            as_of_requirement TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_ideas (
            idea_id TEXT NOT NULL PRIMARY KEY,
            title TEXT NOT NULL,
            raw_description TEXT NOT NULL,
            source TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            candidate_template TEXT NOT NULL DEFAULT '',
            required_factors_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS research_notes (
            note_id TEXT NOT NULL PRIMARY KEY,
            title TEXT NOT NULL,
            note_type TEXT NOT NULL DEFAULT 'idea',
            linked_type TEXT NOT NULL DEFAULT '',
            linked_id TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT 'manual',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    init_research_schema(con)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS data_sources (
            dataset_id TEXT NOT NULL PRIMARY KEY,
            file_path TEXT NOT NULL,
            database_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'UNKNOWN',
            latest_date TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS data_source_tables (
            dataset_id TEXT NOT NULL,
            table_name TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            date_field TEXT NOT NULL DEFAULT '',
            latest_date TEXT NOT NULL DEFAULT '',
            columns_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'UNKNOWN',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (dataset_id, table_name)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunity_themes (
            theme_id TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'observation',
            stage TEXT NOT NULL DEFAULT 'Observation',
            horizon_years INTEGER NOT NULL DEFAULT 0,
            thesis_type TEXT NOT NULL DEFAULT '',
            thesis TEXT NOT NULL DEFAULT '',
            upgrade_rule TEXT NOT NULL DEFAULT '',
            disconfirm_rule TEXT NOT NULL DEFAULT '',
            linked_note_id TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunity_stocks (
            theme_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            watch_level TEXT NOT NULL DEFAULT 'B',
            chain_role TEXT NOT NULL DEFAULT '',
            conviction TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT '',
            source_detail TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            first_observed_date TEXT NOT NULL DEFAULT '',
            thesis TEXT NOT NULL DEFAULT '',
            disconfirm_condition TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            last_monitor_date TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (theme_id, symbol)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS research_monitor_runs (
            run_id TEXT NOT NULL PRIMARY KEY,
            trade_date TEXT NOT NULL,
            theme_id TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunity_direction_rankings (
            trade_date TEXT NOT NULL,
            theme_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            strength_score REAL NOT NULL DEFAULT 0,
            early_signal_score REAL NOT NULL DEFAULT 0,
            maturity_score REAL NOT NULL DEFAULT 0,
            crowding_score REAL NOT NULL DEFAULT 0,
            upgrade_candidate INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, theme_id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_instances (
            strategy_id TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            template_id TEXT NOT NULL,
            status TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            universe TEXT NOT NULL DEFAULT '',
            filters_json TEXT NOT NULL DEFAULT '[]',
            factors_json TEXT NOT NULL DEFAULT '[]',
            construction_json TEXT NOT NULL DEFAULT '{}',
            risk_overlay TEXT NOT NULL DEFAULT '',
            benchmark TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS account_snapshots (
            strategy_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            total_value REAL NOT NULL DEFAULT 0,
            cash REAL NOT NULL DEFAULT 0,
            cash_weight REAL NOT NULL DEFAULT 0,
            position_value REAL NOT NULL DEFAULT 0,
            target_position_weight REAL NOT NULL DEFAULT 0,
            max_abs_drift REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (strategy_id, trade_date)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS account_positions (
            strategy_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            target_weight REAL NOT NULL DEFAULT 0,
            actual_weight REAL NOT NULL DEFAULT 0,
            drift_weight REAL NOT NULL DEFAULT 0,
            target_amount REAL NOT NULL DEFAULT 0,
            actual_amount REAL NOT NULL DEFAULT 0,
            trade_amount REAL NOT NULL DEFAULT 0,
            action TEXT NOT NULL DEFAULT 'HOLD',
            quantity INTEGER NOT NULL DEFAULT 0,
            last_close REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (strategy_id, trade_date, symbol)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_order_batches (
            batch_id TEXT NOT NULL PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            status TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'account_snapshot',
            total_buy_amount REAL NOT NULL DEFAULT 0,
            total_sell_amount REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_orders (
            order_id TEXT NOT NULL PRIMARY KEY,
            batch_id TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            status TEXT NOT NULL,
            target_weight REAL NOT NULL DEFAULT 0,
            actual_weight REAL NOT NULL DEFAULT 0,
            drift_weight REAL NOT NULL DEFAULT 0,
            target_amount REAL NOT NULL DEFAULT 0,
            actual_amount REAL NOT NULL DEFAULT 0,
            trade_amount REAL NOT NULL DEFAULT 0,
            suggested_quantity INTEGER NOT NULL DEFAULT 0,
            suggested_price REAL NOT NULL DEFAULT 0,
            filled_quantity INTEGER NOT NULL DEFAULT 0,
            filled_price REAL NOT NULL DEFAULT 0,
            reject_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_order_audit_events (
            event_id TEXT NOT NULL PRIMARY KEY,
            batch_id TEXT NOT NULL,
            order_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_strategy_instances_enabled ON strategy_instances(enabled, status)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_account_snapshots_strategy ON account_snapshots(strategy_id, trade_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_manual_order_batches_strategy ON manual_order_batches(strategy_id, trade_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_manual_orders_batch ON manual_orders(batch_id, status)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_manual_order_audit_batch ON manual_order_audit_events(batch_id, created_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_factor_contracts_status ON factor_contracts(status, frequency)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_report_strategy_date ON report_index(strategy_id, trade_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_research_notes_type ON research_notes(note_type, modified_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_opportunity_stocks_theme ON opportunity_stocks(theme_id, watch_level)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_research_monitor_runs_theme ON research_monitor_runs(theme_id, trade_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_opportunity_direction_rankings_date ON opportunity_direction_rankings(trade_date, strength_score)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_data_sources_status ON data_sources(status, latest_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_data_source_tables_dataset ON data_source_tables(dataset_id)")
    _ensure_column(con, "opportunity_themes", "horizon_years", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(con, "opportunity_themes", "thesis_type", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "opportunity_themes", "upgrade_rule", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "opportunity_themes", "disconfirm_rule", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "opportunity_stocks", "chain_role", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "opportunity_stocks", "conviction", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "opportunity_stocks", "source_type", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "opportunity_stocks", "source_detail", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "opportunity_stocks", "verification_status", "TEXT NOT NULL DEFAULT 'unverified'")
    _ensure_column(con, "opportunity_stocks", "first_observed_date", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(con, "opportunity_stocks", "evidence_json", "TEXT NOT NULL DEFAULT '{}'")


def _ensure_column(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """为已存在的本地状态库补充新列，保证迁移到 Mac mini 时无需手工 SQL。"""
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {str(row[1]) for row in rows}:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
