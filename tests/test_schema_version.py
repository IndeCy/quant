"""运行状态库 migration 测试。"""

from pathlib import Path
import sqlite3

from runtime.schema_version import apply_schema_migrations, current_schema_version


def test_schema_migrations_are_versioned_and_idempotent(tmp_path: Path) -> None:
    """迁移脚本重复执行不能重复建表或丢失版本。"""
    database = tmp_path / "state.sqlite"

    first = apply_schema_migrations(database)
    second = apply_schema_migrations(database)

    assert first == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert second == []
    assert current_schema_version(database) == 10
    with sqlite3.connect(database) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "schema_migrations",
        "pipeline_runs",
        "run_artifacts",
        "strategy_commit_journal",
        "strategy_risk_policy_events",
        "strategy_risk_recovery_recommendations",
        "research_attempt_reuse_events",
        "strategy_paper_observation_daily",
        "data_sync_runs",
        "data_sync_partitions",
    }.issubset(tables)
