"""历史基线库与Tushare增量库统一视图测试。"""

from pathlib import Path

import duckdb
import pytest

from data.live_market_view import open_live_market_connection
from data.tushare_incremental import IncrementalDuckDBStore


def test_live_view_prefers_increment_and_recomputes_qfq_with_latest_factor(tmp_path: Path) -> None:
    base_path = tmp_path / "base.duckdb"
    increment_path = tmp_path / "increment.duckdb"
    with duckdb.connect(str(base_path)) as con:
        con.execute("CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE)")
        con.execute("INSERT INTO daily VALUES ('AAA.SZ','20240101',10,10,10,10,9,1,11,100,1000),('AAA.SZ','20240102',20,20,20,20,10,10,100,100,2000)")
        con.execute("CREATE TABLE adj_factor(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        con.execute("INSERT INTO adj_factor VALUES ('AAA.SZ','20240101',1),('AAA.SZ','20240102',2)")
        con.execute("CREATE TABLE stock_basic(ts_code VARCHAR, name VARCHAR, list_status VARCHAR, list_date VARCHAR, delist_date VARCHAR)")
        con.execute("CREATE TABLE stock_st(ts_code VARCHAR, trade_date VARCHAR, name VARCHAR)")
        con.execute("CREATE TABLE stock_namechange(ts_code VARCHAR, name VARCHAR, start_date VARCHAR, end_date VARCHAR, ann_date VARCHAR, change_reason VARCHAR)")
        con.execute("CREATE TABLE stock_name_manual(ts_code VARCHAR, name VARCHAR, start_date VARCHAR, end_date VARCHAR)")
    store = IncrementalDuckDBStore(increment_path)
    with duckdb.connect(str(increment_path)) as con:
        con.execute("INSERT INTO daily VALUES ('AAA.SZ','20240103',40,40,40,40,20,20,100,100,4000)")
        con.execute("INSERT INTO adj_factor VALUES ('AAA.SZ','20240103',4)")

    con = open_live_market_connection(base_path, increment_path, lookback_start="20240101")
    try:
        rows = con.execute("SELECT trade_date, close_qfq FROM daily_adj_cache ORDER BY trade_date").fetchall()
    finally:
        con.close()

    assert rows == [("20240101", pytest.approx(2.5)), ("20240102", pytest.approx(10.0)), ("20240103", pytest.approx(40.0))]
