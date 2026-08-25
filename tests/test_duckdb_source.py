"""
DuckDB 数据源适配层测试。
"""

import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest.data as data_module
import backtest.engine as engine_module
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.strategy import BaseStrategy
from data.adjustment import AdjustType
from data.duckdb_source import DuckDBAshareDataSource, summarize_capabilities


class OneShotBuyStrategy(BaseStrategy):
    """测试用单次买入策略。"""

    def __init__(self, symbol: str):
        super().__init__(name="OneShotBuy")
        self.symbol = symbol
        self.sent = False

    def generate_signals(self, data, date):
        if self.sent:
            return {}
        self.sent = True
        return {self.symbol: 100}


def create_sample_duckdb(path: Path) -> None:
    """创建最小 DuckDB 行情库，模拟供应商表结构。"""
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE daily (
            ts_code VARCHAR,
            trade_date VARCHAR,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            pre_close DOUBLE,
            change DOUBLE,
            pct_chg DOUBLE,
            vol DOUBLE,
            amount DOUBLE
        )
        """
    )
    con.execute(
        """
        INSERT INTO daily VALUES
        ('AAA.SZ','20240102',10.0,10.5,9.8,10.2,10.0,0.2,2.0,1000,10000),
        ('AAA.SZ','20240103',11.0,11.1,10.8,11.0,10.2,0.8,7.8,1000,11000),
        ('AAA.SZ','20240105',12.0,12.3,11.8,12.1,11.2,0.9,8.0,1000,12000)
        """
    )
    con.execute("CREATE TABLE adj_factor (ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
    con.execute(
        """
        INSERT INTO adj_factor VALUES
        ('AAA.SZ','20240102',1.0),
        ('AAA.SZ','20240103',1.1),
        ('AAA.SZ','20240105',1.2)
        """
    )
    con.execute(
        """
        CREATE TABLE daily_adj_cache (
            ts_code VARCHAR,
            trade_date VARCHAR,
            adj_factor DOUBLE,
            first_adj DOUBLE,
            last_adj DOUBLE,
            open_qfq DOUBLE,
            high_qfq DOUBLE,
            low_qfq DOUBLE,
            close_qfq DOUBLE,
            pre_close_qfq DOUBLE,
            change_qfq DOUBLE,
            pct_chg_qfq DOUBLE,
            open_hfq DOUBLE,
            high_hfq DOUBLE,
            low_hfq DOUBLE,
            close_hfq DOUBLE,
            pre_close_hfq DOUBLE,
            change_hfq DOUBLE,
            pct_chg_hfq DOUBLE
        )
        """
    )
    con.execute(
        """
        INSERT INTO daily_adj_cache VALUES
        ('AAA.SZ','20240102',1.0,1.0,1.2,8.3,8.7,8.2,8.5,8.3,0.2,2.0,10.0,10.5,9.8,10.2,10.0,0.2,2.0),
        ('AAA.SZ','20240103',1.1,1.0,1.2,10.1,10.2,9.9,10.1,9.4,0.7,7.8,12.1,12.2,11.9,12.1,11.2,0.9,7.8),
        ('AAA.SZ','20240105',1.2,1.0,1.2,12.0,12.3,11.8,12.1,11.2,0.9,8.0,14.4,14.8,14.2,14.5,13.4,1.1,8.0)
        """
    )
    con.execute("CREATE TABLE stock_basic (ts_code VARCHAR, name VARCHAR, list_status VARCHAR, list_date VARCHAR, delist_date VARCHAR)")
    con.execute("INSERT INTO stock_basic VALUES ('AAA.SZ','测试A','L','20200101',NULL)")
    con.execute("CREATE TABLE stock_st (ts_code VARCHAR, trade_date VARCHAR, name VARCHAR)")
    con.execute("CREATE TABLE stock_namechange (ts_code VARCHAR, name VARCHAR, start_date VARCHAR, end_date VARCHAR, ann_date VARCHAR, change_reason VARCHAR)")
    con.close()


class TestDuckDBAshareDataSource(unittest.TestCase):
    """验证 DuckDB 适配层不绕过统一 schema 和口径约束。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "sample.duckdb"
        create_sample_duckdb(self.db_path)
        self.source = DuckDBAshareDataSource(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_tables_and_capabilities(self):
        summaries = self.source.inspect_tables()
        capabilities = summarize_capabilities(summaries)

        self.assertIn("daily", {summary.table_name for summary in summaries})
        self.assertTrue(capabilities["日线行情"])
        self.assertTrue(capabilities["股票基础信息"])
        self.assertTrue(capabilities["交易日历"])
        self.assertFalse(capabilities["财务数据"])

    def test_daily_bars_require_explicit_adjust_policy_and_schema(self):
        bars = self.source.get_daily_bars("AAA.SZ", "2024-01-02", "2024-01-05", adjust_policy="qfq")

        self.assertEqual(bars.attrs["adjust"], "qfq")
        self.assertEqual(list(bars.index), list(pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05"])))
        for column in [
            "code",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adj_factor",
            "is_suspended",
            "limit_up",
            "limit_down",
        ]:
            self.assertIn(column, bars.columns)
        self.assertAlmostEqual(float(bars.loc[pd.Timestamp("2024-01-03"), "open"]), 10.1)

    def test_data_manager_loads_duckdb_symbol_through_source(self):
        manager = DataManager(self.source, default_adjust=AdjustType.NONE)
        manager.load_symbol("AAA.SZ", "2024-01-02", "2024-01-05", adjust="hfq")

        bars = manager.get_data("AAA.SZ")

        self.assertEqual(manager.get_adjust("AAA.SZ"), AdjustType.HFQ)
        self.assertEqual(bars.attrs["adjust"], "hfq")
        self.assertAlmostEqual(float(bars.loc[pd.Timestamp("2024-01-05"), "close"]), 14.5)

    def test_engine_uses_duckdb_calendar_and_missing_trade_day_blocks_execution(self):
        manager = DataManager(self.source)
        manager.load_symbol("AAA.SZ", "2024-01-02", "2024-01-05", adjust="none")
        engine = BacktestEngine(manager, OneShotBuyStrategy("AAA.SZ"), commission_rate=0.0, slippage=0.0)

        engine.run()

        self.assertEqual(engine.trades[0]["signal_date"], pd.Timestamp("2024-01-02"))
        self.assertEqual(engine.trades[0]["date"], pd.Timestamp("2024-01-03"))
        self.assertNotIn(pd.Timestamp("2024-01-04"), engine.daily_values[0].values())
        self.assertEqual(
            engine.trading_calendar.trading_days("2024-01-02", "2024-01-05"),
            [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-05")],
        )

    def test_financial_portal_requires_publish_date_or_ann_date(self):
        with self.assertRaisesRegex(ValueError, "publish_date/ann_date"):
            self.source.get_financial_portal()

    def test_backtest_modules_do_not_import_duckdb_directly(self):
        """业务模块不能绕过数据源适配层直接访问 DuckDB。"""
        self.assertNotIn("import duckdb", inspect.getsource(data_module))
        self.assertNotIn("import duckdb", inspect.getsource(engine_module))


if __name__ == "__main__":
    unittest.main()
