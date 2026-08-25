"""
研究基准工具测试。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from backtest.research_benchmark import align_benchmark_return, load_hs300_benchmark, load_hs300_or_proxy


class TestResearchBenchmark(unittest.TestCase):
    """验证沪深300基准只使用本地 DuckDB 已有行情。"""

    def test_load_hs300_or_proxy_returns_unavailable_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.duckdb"
            con = duckdb.connect(str(path))
            con.execute("CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, close_qfq DOUBLE)")
            con.execute("CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR, amount DOUBLE)")
            con.execute(
                """
                INSERT INTO daily_adj_cache VALUES
                ('AAA.SZ','20240102',10),('AAA.SZ','20240103',11),
                ('BBB.SZ','20240102',20),('BBB.SZ','20240103',21)
                """
            )
            con.execute(
                """
                INSERT INTO daily VALUES
                ('AAA.SZ','20240102',1000),('AAA.SZ','20240103',1000),
                ('BBB.SZ','20240102',900),('BBB.SZ','20240103',900)
                """
            )

            curve, label = load_hs300_or_proxy(con, "20240102")

            self.assertEqual(label, "HS300_UNAVAILABLE_IN_DUCKDB")
            self.assertTrue(curve.empty)
            con.close()

    def test_align_benchmark_return_uses_strategy_dates(self):
        strategy = pd.Series([100.0, 110.0], index=pd.to_datetime(["2024-01-02", "2024-01-04"]))
        benchmark = pd.Series(
            [1.0, 1.05, 1.10],
            index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        )

        result = align_benchmark_return(strategy, benchmark)

        self.assertAlmostEqual(result, 0.10)

    def test_load_hs300_benchmark_uses_local_etf_when_index_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stock_path = Path(temp_dir) / "stock.duckdb"
            daily_path = Path(temp_dir) / "fund_daily.duckdb"
            basic_path = Path(temp_dir) / "fund_basic.duckdb"
            con = duckdb.connect(str(stock_path))
            con.execute("CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, close_qfq DOUBLE)")
            con2 = duckdb.connect(str(daily_path))
            con2.execute("CREATE TABLE etf_lof_reits_daily_adj(ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, vol DOUBLE, amount DOUBLE, adj_factor DOUBLE, fund_name VARCHAR, exchange VARCHAR, fund_category VARCHAR)")
            con2.execute("INSERT INTO etf_lof_reits_daily_adj VALUES ('510300.SH','20240102',1,1,1,1,100,1000,1,'沪深300ETF','SH','ETF'),('510300.SH','20240103',1.1,1.1,1.1,1.1,100,1100,1,'沪深300ETF','SH','ETF')")
            con2.close()
            con3 = duckdb.connect(str(basic_path))
            con3.execute("CREATE TABLE etf_lof_reits_basic_export(ts_code VARCHAR, name VARCHAR, index_code VARCHAR, index_name VARCHAR, list_date VARCHAR, fund_category VARCHAR)")
            con3.execute("INSERT INTO etf_lof_reits_basic_export VALUES ('510300.SH','沪深300ETF','000300.SH','沪深300指数','20120528','ETF')")
            con3.close()

            curve, label = load_hs300_benchmark(con, "20240102", str(daily_path), str(basic_path))

            self.assertEqual(label, "HS300_ETF:510300.SH")
            self.assertAlmostEqual(float(curve.iloc[-1]), 1.1)
            con.close()

    def test_load_hs300_benchmark_applies_etf_adjust_factor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stock_path = Path(temp_dir) / "stock.duckdb"
            daily_path = Path(temp_dir) / "fund_daily.duckdb"
            basic_path = Path(temp_dir) / "fund_basic.duckdb"
            con = duckdb.connect(str(stock_path))
            con.execute("CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, close_qfq DOUBLE)")
            con2 = duckdb.connect(str(daily_path))
            con2.execute("CREATE TABLE etf_lof_reits_daily_adj(ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, vol DOUBLE, amount DOUBLE, adj_factor DOUBLE, fund_name VARCHAR, exchange VARCHAR, fund_category VARCHAR)")
            con2.execute("INSERT INTO etf_lof_reits_daily_adj VALUES ('510300.SH','20231229',1,1,1,1,100,1000,1,'沪深300ETF','SH','ETF'),('510300.SH','20240102',1.1,1.1,1.1,1.1,100,1100,1.1,'沪深300ETF','SH','ETF')")
            con2.close()
            con3 = duckdb.connect(str(basic_path))
            con3.execute("CREATE TABLE etf_lof_reits_basic_export(ts_code VARCHAR, name VARCHAR, index_code VARCHAR, index_name VARCHAR, list_date VARCHAR, fund_category VARCHAR)")
            con3.execute("INSERT INTO etf_lof_reits_basic_export VALUES ('510300.SH','沪深300ETF','000300.SH','沪深300指数','20120528','ETF')")
            con3.close()

            curve, _ = load_hs300_benchmark(con, "20240101", str(daily_path), str(basic_path))

            self.assertAlmostEqual(float(curve.iloc[-1] / curve.iloc[0] - 1), 0.21)
            con.close()


if __name__ == "__main__":
    unittest.main()
