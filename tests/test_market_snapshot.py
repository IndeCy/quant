"""统一 base+increment 行情快照测试。"""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.market_snapshot import create_fund_market_snapshot, create_market_snapshot
from data.tushare_benchmark_incremental import BenchmarkIncrementalStore, FUND_ADJ_COLUMNS, MARKET_COLUMNS
from data.tushare_incremental import IncrementalDuckDBStore


def test_market_snapshot_applies_increment_override_and_as_of_boundary(tmp_path: Path) -> None:
    """增量覆盖基线，同时快照不得读取 as-of 之后的数据和因子。"""
    base_path, increment_path = _seed_market_databases(tmp_path)

    snapshot = create_market_snapshot(
        base_path,
        increment_path,
        "20240103",
        lookback_start="20240101",
        adjust_policy="qfq",
    )
    con = snapshot.connect()
    try:
        rows = con.execute("SELECT trade_date, close FROM daily ORDER BY trade_date").fetchall()
        factors = con.execute("SELECT trade_date, adj_factor FROM adj_factor ORDER BY trade_date").fetchall()
    finally:
        con.close()
    bars = snapshot.load_daily_bars("AAA.SZ")

    assert rows == [("20240101", 10.0), ("20240102", 22.0), ("20240103", 40.0)]
    assert factors == [("20240101", 1.0), ("20240102", 2.2), ("20240103", 4.0)]
    assert bars.index.max() == pd.Timestamp("2024-01-03")
    assert bars.loc[pd.Timestamp("2024-01-01"), "close"] == pytest.approx(2.5)
    assert bars.attrs["adjust"] == "qfq"
    assert bars.attrs["snapshot_id"] == snapshot.snapshot_id


def test_market_snapshot_identity_is_stable_and_date_sensitive(tmp_path: Path) -> None:
    """相同文件与口径生成同一 ID，改变 as-of 日期必须形成新版本。"""
    base_path, increment_path = _seed_market_databases(tmp_path)

    first = create_market_snapshot(base_path, increment_path, "20240103", lookback_start="20240101")
    same = create_market_snapshot(base_path, increment_path, "20240103", lookback_start="20240101")
    next_date = create_market_snapshot(base_path, increment_path, "20240104", lookback_start="20240101")

    assert first.snapshot_id == same.snapshot_id
    assert first.snapshot_id != next_date.snapshot_id


def test_fund_market_snapshot_merges_increment_and_applies_qfq(tmp_path: Path) -> None:
    """基金快照应覆盖基线重叠日，并且不得读取 as-of 之后的增量。"""
    base_path = tmp_path / "fund_base.duckdb"
    increment_path = tmp_path / "fund_increment.duckdb"
    with duckdb.connect(str(base_path)) as con:
        con.execute(
            """
            CREATE TABLE etf_lof_reits_daily_adj(
                ts_code VARCHAR, trade_date VARCHAR,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE,
                vol DOUBLE, amount DOUBLE, adj_factor DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO etf_lof_reits_daily_adj VALUES
            ('518880.SH','20240101',10,10,10,10,9,1,11,100,1000,1),
            ('518880.SH','20240102',20,20,20,20,10,10,100,100,2000,2)
            """
        )
    store = BenchmarkIncrementalStore(increment_path)
    store.upsert_fund(
        pd.DataFrame(
            [
                _fund_market_row("518880.SH", "20240102", 22.0),
                _fund_market_row("518880.SH", "20240103", 40.0),
                _fund_market_row("518880.SH", "20240104", 80.0),
            ],
            columns=MARKET_COLUMNS,
        )
    )
    store.upsert_fund_adj(
        pd.DataFrame(
            [
                ["518880.SH", "20240102", 2.2],
                ["518880.SH", "20240103", 4.0],
                ["518880.SH", "20240104", 8.0],
            ],
            columns=FUND_ADJ_COLUMNS,
        )
    )

    snapshot = create_fund_market_snapshot(
        base_path,
        increment_path,
        "20240103",
        lookback_start="20240101",
        adjust_policy="qfq",
    )
    bars = snapshot.load_daily_bars("518880.SH")

    assert list(bars.index) == list(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    assert bars.loc[pd.Timestamp("2024-01-01"), "close"] == pytest.approx(2.5)
    assert bars.loc[pd.Timestamp("2024-01-02"), "close"] == pytest.approx(12.1)
    assert bars.loc[pd.Timestamp("2024-01-03"), "close"] == pytest.approx(40.0)
    assert bars.attrs["adjust"] == "qfq"
    assert bars.attrs["source"] == "fund_market_data_snapshot"


def _seed_market_databases(tmp_path: Path) -> tuple[Path, Path]:
    """构造带重叠日和未来日的最小基线、增量库。"""
    base_path = tmp_path / "base.duckdb"
    increment_path = tmp_path / "increment.duckdb"
    with duckdb.connect(str(base_path)) as con:
        con.execute(
            "CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, "
            "close DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE)"
        )
        con.execute(
            "INSERT INTO daily VALUES "
            "('AAA.SZ','20240101',10,10,10,10,9,1,11,100,1000),"
            "('AAA.SZ','20240102',20,20,20,20,10,10,100,100,2000)"
        )
        con.execute("CREATE TABLE adj_factor(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        con.execute("INSERT INTO adj_factor VALUES ('AAA.SZ','20240101',1),('AAA.SZ','20240102',2)")
        con.execute("CREATE TABLE stock_basic(ts_code VARCHAR, name VARCHAR)")
        con.execute("CREATE TABLE stock_st(ts_code VARCHAR, trade_date VARCHAR, name VARCHAR)")
        con.execute("CREATE TABLE stock_namechange(ts_code VARCHAR, name VARCHAR)")
        con.execute("CREATE TABLE stock_name_manual(ts_code VARCHAR, name VARCHAR)")
    IncrementalDuckDBStore(increment_path)
    with duckdb.connect(str(increment_path)) as con:
        con.execute(
            "INSERT INTO daily VALUES "
            "('AAA.SZ','20240102',22,22,22,22,10,12,120,100,2200),"
            "('AAA.SZ','20240103',40,40,40,40,22,18,82,100,4000),"
            "('AAA.SZ','20240104',80,80,80,80,40,40,100,100,8000)"
        )
        con.execute(
            "INSERT INTO adj_factor VALUES "
            "('AAA.SZ','20240102',2.2),('AAA.SZ','20240103',4),('AAA.SZ','20240104',8)"
        )
    return base_path, increment_path


def _fund_market_row(symbol: str, trade_date: str, close: float) -> list[object]:
    """构造 Tushare 基金日线标准行。"""
    return [
        symbol,
        trade_date,
        close,
        close,
        close,
        close,
        close,
        0.0,
        0.0,
        100.0,
        close * 100.0,
    ]
