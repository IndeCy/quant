"""数据质量门禁测试。"""

from pathlib import Path

import duckdb
import pytest

from runtime.data_quality_gate import DataQualityError, run_data_quality_gate
from runtime.paths import RuntimePaths


def _seed_valid_data(paths: RuntimePaths) -> None:
    """写入最小可信行情和基准数据。"""
    paths.ensure_directories()
    with duckdb.connect(str(paths.live_market_increment_path)) as con:
        con.execute("CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        con.execute("CREATE TABLE adj_factor(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        con.execute("INSERT INTO daily VALUES ('000001.SZ', '20260702', 10.0)")
        con.execute("INSERT INTO adj_factor VALUES ('000001.SZ', '20260702', 1.0)")
    with duckdb.connect(str(paths.benchmark_increment_path)) as con:
        con.execute("CREATE TABLE fund_daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        con.execute("CREATE TABLE fund_adj(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        con.execute("CREATE TABLE index_daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        con.execute("INSERT INTO fund_daily VALUES ('510300.SH', '20260702', 5.0)")
        con.execute("INSERT INTO fund_adj VALUES ('510300.SH', '20260702', 1.0)")
        con.execute("INSERT INTO index_daily VALUES ('000001.SH', '20260702', 3000.0)")


def test_data_quality_gate_passes_for_required_sources(tmp_path: Path) -> None:
    """关键行情、复权和基准都齐备时门禁通过。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_valid_data(paths)

    result = run_data_quality_gate(paths=paths, min_trade_date="20260702")

    assert result["status"] == "PASS"
    assert result["failed_count"] == 0
    assert {item["dataset_id"] for item in result["checks"]} == {
        "live_market_increment_duckdb",
        "benchmark_increment_duckdb",
    }


def test_data_quality_gate_fails_when_adjust_factor_missing(tmp_path: Path) -> None:
    """A股复权因子缺失时必须阻断，不能继续生成策略建议。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    with duckdb.connect(str(paths.live_market_increment_path)) as con:
        con.execute("CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        con.execute("INSERT INTO daily VALUES ('000001.SZ', '20260702', 10.0)")
    with duckdb.connect(str(paths.benchmark_increment_path)) as con:
        con.execute("CREATE TABLE fund_daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        con.execute("CREATE TABLE fund_adj(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        con.execute("CREATE TABLE index_daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        con.execute("INSERT INTO fund_daily VALUES ('510300.SH', '20260702', 5.0)")
        con.execute("INSERT INTO fund_adj VALUES ('510300.SH', '20260702', 1.0)")
        con.execute("INSERT INTO index_daily VALUES ('000001.SH', '20260702', 3000.0)")

    with pytest.raises(DataQualityError, match="adj_factor"):
        run_data_quality_gate(paths=paths, min_trade_date="20260702", raise_on_fail=True)


def test_data_quality_gate_fails_when_benchmark_is_stale(tmp_path: Path) -> None:
    """基准最新日期早于要求日期时必须失败。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_valid_data(paths)
    paths.benchmark_increment_path.unlink()
    with duckdb.connect(str(paths.benchmark_increment_path)) as con:
        con.execute("CREATE TABLE fund_daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        con.execute("CREATE TABLE fund_adj(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        con.execute("CREATE TABLE index_daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        con.execute("INSERT INTO fund_daily VALUES ('510300.SH', '20260701', 5.0)")
        con.execute("INSERT INTO fund_adj VALUES ('510300.SH', '20260701', 1.0)")
        con.execute("INSERT INTO index_daily VALUES ('000001.SH', '20260701', 3000.0)")

    result = run_data_quality_gate(paths=paths, min_trade_date="20260702")

    assert result["status"] == "FAIL"
    assert any("早于要求日期" in item["message"] for item in result["checks"])
