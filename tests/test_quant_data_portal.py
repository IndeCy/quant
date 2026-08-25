"""统一量化数据快照测试。"""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.dataset_contract import DatasetBinding, DatasetContract
from data.financial import FinancialDataPortal, FinancialStatementStore
from data.market_snapshot import create_fund_market_snapshot, create_market_snapshot
from data.quant_data_portal import QuantDataSnapshot
from data.tushare_benchmark_incremental import BenchmarkIncrementalStore
from data.tushare_incremental import IncrementalDuckDBStore


def test_snapshot_routes_market_financial_and_extension_data(tmp_path: Path) -> None:
    stock_base, stock_increment = _stock_databases(tmp_path)
    fund_base, fund_increment = _fund_databases(tmp_path)
    extension = tmp_path / "extension.duckdb"
    with duckdb.connect(str(extension)) as con:
        con.execute("CREATE TABLE daily_basic(trade_date VARCHAR, ts_code VARCHAR, pe_ttm DOUBLE, PRIMARY KEY(trade_date, ts_code))")
        con.execute("INSERT INTO daily_basic VALUES ('20240102','AAA.SZ',10),('20240103','AAA.SZ',11),('20240104','AAA.SZ',12)")
    contract = DatasetContract(
        dataset_id="market.daily_basic",
        table_name="daily_basic",
        primary_key=("trade_date", "ts_code"),
        date_field="trade_date",
        symbol_field="ts_code",
    )
    portal = QuantDataSnapshot(
        as_of_date="20240103",
        stock_market=create_market_snapshot(stock_base, stock_increment, "20240103", lookback_start="20240101"),
        fund_market=create_fund_market_snapshot(fund_base, fund_increment, "20240103", lookback_start="20240101"),
        financial_portal=_financial_portal(),
        datasets=[DatasetBinding(contract, extension)],
    )

    bars = portal.stock_bars("AAA.SZ", start_date="20240101")
    valuation = portal.load_dataset("market.daily_basic", latest_only=True, symbols=["AAA.SZ"])
    financial = portal.financial_snapshot("AAA.SZ", fields=["roe"])

    assert bars.index.max() == pd.Timestamp("2024-01-03")
    assert valuation[["trade_date", "pe_ttm"]].values.tolist() == [["20240103", 11.0]]
    assert valuation.attrs["snapshot_id"] == portal.snapshot_id
    assert financial == {"roe": 12.0}


def test_dated_dataset_requires_bounded_query_and_valid_columns(tmp_path: Path) -> None:
    portal = _portal_with_extension(tmp_path)

    with pytest.raises(ValueError, match="start_date 或 latest_only"):
        portal.load_dataset("market.daily_basic")
    with pytest.raises(ValueError, match="不存在的字段"):
        portal.load_dataset("market.daily_basic", latest_only=True, columns=["unknown"])
    with pytest.raises(ValueError, match="不能晚于"):
        portal.load_dataset("market.daily_basic", start_date="20240104")


def test_static_dataset_can_be_read_without_date_range(tmp_path: Path) -> None:
    portal = _portal_with_extension(tmp_path, static=True)

    result = portal.load_dataset("reference.industry", symbols=["AAA.SZ"])

    assert result[["ts_code", "industry"]].values.tolist() == [["AAA.SZ", "银行"]]


def _portal_with_extension(tmp_path: Path, static: bool = False) -> QuantDataSnapshot:
    stock_base, stock_increment = _stock_databases(tmp_path)
    fund_base, fund_increment = _fund_databases(tmp_path)
    extension = tmp_path / "extension.duckdb"
    with duckdb.connect(str(extension)) as con:
        if static:
            con.execute("CREATE TABLE industry(ts_code VARCHAR PRIMARY KEY, industry VARCHAR)")
            con.execute("INSERT INTO industry VALUES ('AAA.SZ','银行'),('BBB.SZ','消费')")
            contract = DatasetContract("reference.industry", "industry", ("ts_code",), symbol_field="ts_code")
        else:
            con.execute("CREATE TABLE daily_basic(trade_date VARCHAR, ts_code VARCHAR, pe_ttm DOUBLE, PRIMARY KEY(trade_date, ts_code))")
            con.execute("INSERT INTO daily_basic VALUES ('20240102','AAA.SZ',10),('20240103','AAA.SZ',11)")
            contract = DatasetContract("market.daily_basic", "daily_basic", ("trade_date", "ts_code"), "trade_date", "ts_code")
    return QuantDataSnapshot(
        as_of_date="20240103",
        stock_market=create_market_snapshot(stock_base, stock_increment, "20240103", lookback_start="20240101"),
        fund_market=create_fund_market_snapshot(fund_base, fund_increment, "20240103", lookback_start="20240101"),
        financial_portal=_financial_portal(),
        datasets=[DatasetBinding(contract, extension)],
    )


def _financial_portal() -> FinancialDataPortal:
    records = pd.DataFrame(
        [
            {"symbol":"AAA.SZ","report_period":"2023-09-30","publish_date":"2023-10-30","statement_type":"indicator","field_name":"roe","field_value":10,"source":"test"},
            {"symbol":"AAA.SZ","report_period":"2023-12-31","publish_date":"2024-01-03","statement_type":"indicator","field_name":"roe","field_value":12,"source":"test"},
            {"symbol":"AAA.SZ","report_period":"2024-03-31","publish_date":"2024-04-30","statement_type":"indicator","field_name":"roe","field_value":99,"source":"test"},
        ]
    )
    return FinancialDataPortal(FinancialStatementStore(records))


def _stock_databases(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "stock_base.duckdb"
    increment = tmp_path / "stock_increment.duckdb"
    with duckdb.connect(str(base)) as con:
        con.execute("CREATE TABLE daily(ts_code VARCHAR,trade_date VARCHAR,open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,pre_close DOUBLE,change DOUBLE,pct_chg DOUBLE,vol DOUBLE,amount DOUBLE)")
        con.execute("INSERT INTO daily VALUES ('AAA.SZ','20240101',10,10,10,10,9,1,11,100,1000)")
        con.execute("CREATE TABLE adj_factor(ts_code VARCHAR,trade_date VARCHAR,adj_factor DOUBLE)")
        con.execute("INSERT INTO adj_factor VALUES ('AAA.SZ','20240101',1)")
        con.execute("CREATE TABLE stock_basic(ts_code VARCHAR,name VARCHAR)")
        con.execute("CREATE TABLE stock_st(ts_code VARCHAR,trade_date VARCHAR,name VARCHAR)")
        con.execute("CREATE TABLE stock_namechange(ts_code VARCHAR,name VARCHAR)")
        con.execute("CREATE TABLE stock_name_manual(ts_code VARCHAR,name VARCHAR)")
    IncrementalDuckDBStore(increment)
    with duckdb.connect(str(increment)) as con:
        con.execute("INSERT INTO daily VALUES ('AAA.SZ','20240103',12,12,12,12,10,2,20,100,1200)")
        con.execute("INSERT INTO adj_factor VALUES ('AAA.SZ','20240103',1)")
    return base, increment


def _fund_databases(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "fund_base.duckdb"
    increment = tmp_path / "fund_increment.duckdb"
    with duckdb.connect(str(base)) as con:
        con.execute("CREATE TABLE etf_lof_reits_daily_adj(ts_code VARCHAR,trade_date VARCHAR,open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,pre_close DOUBLE,change DOUBLE,pct_chg DOUBLE,vol DOUBLE,amount DOUBLE,adj_factor DOUBLE)")
        con.execute("INSERT INTO etf_lof_reits_daily_adj VALUES ('510300.SH','20240101',4,4,4,4,4,0,0,100,400,1)")
    BenchmarkIncrementalStore(increment)
    return base, increment
