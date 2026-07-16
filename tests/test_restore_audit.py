"""运行目录恢复验收测试。"""

from pathlib import Path
import sqlite3

import duckdb

from runtime.paths import RuntimePaths
from runtime.restore_audit import audit_runtime_restore


def test_restore_audit_validates_database_contents_not_only_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """完整迁移目录应通过数据库可读性和外部文件检查。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    config_path = tmp_path / ".env.properties"
    config_path.write_text("TUSHARE_TOKEN=test\n", encoding="utf-8")
    frontend_index = tmp_path / "frontend" / "dist" / "index.html"
    frontend_index.parent.mkdir(parents=True)
    frontend_index.write_text("ok", encoding="utf-8")
    base_path = tmp_path / "base.duckdb"
    monkeypatch.setenv("QUANT_BASE_MARKET_DB", str(base_path))

    for path in [paths.system_state_path, paths.monitoring_path, paths.paper_trading_path]:
        with sqlite3.connect(path) as con:
            con.execute("CREATE TABLE health(id INTEGER)")
    for path in [paths.live_market_increment_path, paths.benchmark_increment_path, base_path]:
        with duckdb.connect(str(path)) as con:
            con.execute("CREATE TABLE health(id INTEGER)")

    result = audit_runtime_restore(paths, config_path, frontend_index)

    assert result["status"] == "READY"
    assert result["failed_count"] == 0


def test_restore_audit_reports_missing_runtime_files(tmp_path: Path) -> None:
    """缺文件时应返回结构化失败清单，供迁移脚本直接阻断启动。"""
    paths = RuntimePaths(tmp_path / "runtime")

    result = audit_runtime_restore(paths, tmp_path / "missing.properties", tmp_path / "missing-index.html")

    assert result["status"] == "NOT_READY"
    assert result["failed_count"] > 0
    assert any(item["name"] == "system_state" and item["status"] == "FAIL" for item in result["checks"])
