"""运行状态库 migration 测试。"""

from pathlib import Path
import sqlite3

from runtime.schema_version import apply_schema_migrations, current_schema_version


def test_schema_migrations_are_versioned_and_idempotent(tmp_path: Path) -> None:
    """迁移脚本重复执行不能重复建表或丢失版本。"""
    database = tmp_path / "state.sqlite"

    first = apply_schema_migrations(database)
    second = apply_schema_migrations(database)

    assert first == [1, 2, 3]
    assert second == []
    assert current_schema_version(database) == 3
    with sqlite3.connect(database) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"schema_migrations", "pipeline_runs", "run_artifacts", "strategy_commit_journal"}.issubset(tables)
