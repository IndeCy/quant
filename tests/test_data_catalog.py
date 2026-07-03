"""数据目录测试。"""

from pathlib import Path
import sqlite3

import duckdb

from runtime.data_catalog import discover_data_sources
from runtime.data_catalog_runner import refresh_data_catalog
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_data_catalog_discovers_duckdb_and_sqlite_sources(tmp_path: Path) -> None:
    """Data Catalog 应识别本地数据库文件并提取最新交易日期。"""
    duckdb_path = tmp_path / "daily.duckdb"
    sqlite_path = tmp_path / "monitoring.sqlite3"
    with duckdb.connect(str(duckdb_path)) as con:
        con.execute(
            """
            CREATE TABLE daily_bars(
                trade_date VARCHAR,
                symbol VARCHAR,
                close DOUBLE
            )
            """
        )
        con.execute("INSERT INTO daily_bars VALUES ('20260701', '000001.SZ', 10.0)")
        con.execute("INSERT INTO daily_bars VALUES ('20260702', '000001.SZ', 10.2)")
    with sqlite3.connect(sqlite_path) as con:
        con.execute("CREATE TABLE strategy_nav(trade_date TEXT NOT NULL, nav REAL NOT NULL)")
        con.execute("INSERT INTO strategy_nav VALUES ('20260701', 1.01)")

    entries = discover_data_sources([tmp_path])

    by_name = {Path(item["file_path"]).name: item for item in entries}
    assert by_name["daily.duckdb"]["database_type"] == "duckdb"
    assert by_name["daily.duckdb"]["latest_date"] == "20260702"
    assert by_name["daily.duckdb"]["tables"][0]["table_name"] == "daily_bars"
    assert by_name["monitoring.sqlite3"]["database_type"] == "sqlite"
    assert by_name["monitoring.sqlite3"]["latest_date"] == "20260701"


def test_repository_persists_data_catalog(tmp_path: Path) -> None:
    """系统状态库应保存数据源和表级字段口径。"""
    paths = RuntimePaths(tmp_path / "runtime")
    repository = SystemRepository(paths.system_state_path)
    source = {
        "dataset_id": "data_daily_duckdb",
        "file_path": str(tmp_path / "daily.duckdb"),
        "database_type": "duckdb",
        "size_bytes": 1024,
        "status": "OK",
        "latest_date": "20260702",
        "description": "日线行情",
        "config": {"adjust_policy": "qfq"},
        "tables": [
            {
                "table_name": "daily_bars",
                "row_count": 2,
                "date_field": "trade_date",
                "latest_date": "20260702",
                "columns": ["trade_date", "symbol", "close"],
                "status": "OK",
            }
        ],
    }

    repository.upsert_data_source(source)
    detail = repository.load_data_source("data_daily_duckdb")
    sources = repository.list_data_sources()

    assert detail is not None
    assert detail["config"]["adjust_policy"] == "qfq"
    assert detail["tables"][0]["columns"] == ["trade_date", "symbol", "close"]
    assert sources[0]["dataset_id"] == "data_daily_duckdb"


def test_refresh_data_catalog_writes_repository(tmp_path: Path) -> None:
    """刷新任务应把扫描结果写入系统状态库。"""
    paths = RuntimePaths(tmp_path / "runtime")
    data_dir = tmp_path / "dataset"
    data_dir.mkdir()
    duckdb_path = data_dir / "daily.duckdb"
    with duckdb.connect(str(duckdb_path)) as con:
        con.execute("CREATE TABLE daily(trade_date VARCHAR, close DOUBLE)")
        con.execute("INSERT INTO daily VALUES ('20260702', 10.2)")

    result = refresh_data_catalog(paths=paths, roots=[data_dir])
    sources = SystemRepository(paths.system_state_path).list_data_sources()

    assert result["status"] == "SUCCESS"
    assert result["source_count"] == 1
    assert sources[0]["dataset_id"] == "daily_duckdb"
    assert sources[0]["latest_date"] == "20260702"
