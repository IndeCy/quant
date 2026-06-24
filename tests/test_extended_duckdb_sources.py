"""
新增 DuckDB 财务与基金数据源适配测试。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from data.duckdb_source import DuckDBAshareDataSource
from data.financial_duckdb_source import DuckDBFinancialDataSource
from data.fund_duckdb_source import DuckDBFundDataSource


class TestExtendedDuckDBSources(unittest.TestCase):
    """验证新增 DuckDB 数据能进入统一数据源层。"""

    def test_financial_source_uses_f_ann_date_as_as_of_publish_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fina_indicator.duckdb"
            con = duckdb.connect(str(path))
            con.execute(
                """
                CREATE TABLE default_table(
                  ts_code VARCHAR,
                  end_date VARCHAR,
                  ann_date VARCHAR,
                  f_ann_date VARCHAR,
                  roe DOUBLE,
                  gross_margin DOUBLE
                )
                """
            )
            con.execute(
                """
                INSERT INTO default_table VALUES
                ('AAA.SZ','20231231','20240428','20240430',12.0,35.0),
                ('AAA.SZ','20230930','20231025','20231027',9.0,30.0)
                """
            )
            con.close()

            source = DuckDBFinancialDataSource({"fina_indicator": path})
            portal = source.get_financial_portal(fields_by_statement={"fina_indicator": ["roe"]})

            self.assertEqual(portal.get_financial_snapshot("AAA.SZ", "2024-04-29")["roe"], 9.0)
            self.assertEqual(portal.get_financial_snapshot("AAA.SZ", "2024-04-30")["roe"], 12.0)

    def test_ashare_source_can_attach_financial_duckdb_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            daily_path = Path(temp_dir) / "daily.duckdb"
            fina_path = Path(temp_dir) / "fina_indicator.duckdb"
            con = duckdb.connect(str(daily_path))
            con.execute("CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE)")
            con.execute("CREATE TABLE adj_factor(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
            con.execute("CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE, open_qfq DOUBLE, high_qfq DOUBLE, low_qfq DOUBLE, close_qfq DOUBLE, pre_close_qfq DOUBLE, open_hfq DOUBLE, high_hfq DOUBLE, low_hfq DOUBLE, close_hfq DOUBLE, pre_close_hfq DOUBLE)")
            con.execute("CREATE TABLE stock_basic(ts_code VARCHAR, name VARCHAR)")
            con.execute("CREATE TABLE stock_st(ts_code VARCHAR, trade_date VARCHAR, name VARCHAR)")
            con.close()
            con = duckdb.connect(str(fina_path))
            con.execute("CREATE TABLE default_table(ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR, roe DOUBLE)")
            con.execute("INSERT INTO default_table VALUES ('AAA.SZ','20231231','20240430',11.0)")
            con.close()

            source = DuckDBAshareDataSource(daily_path, financial_db_paths={"fina_indicator": fina_path})
            portal = source.get_financial_portal(fields_by_statement={"fina_indicator": ["roe"]})

            self.assertEqual(portal.get_financial_snapshot("AAA.SZ", "2024-05-01")["roe"], 11.0)

    def test_fund_source_reads_bars_and_finds_hs300_products(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            daily_path = Path(temp_dir) / "fund_daily.duckdb"
            basic_path = Path(temp_dir) / "fund_basic.duckdb"
            con = duckdb.connect(str(daily_path))
            con.execute(
                """
                CREATE TABLE etf_lof_reits_daily_adj(
                  ts_code VARCHAR,
                  trade_date VARCHAR,
                  open DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  close DOUBLE,
                  vol DOUBLE,
                  amount DOUBLE,
                  adj_factor DOUBLE,
                  fund_name VARCHAR,
                  exchange VARCHAR,
                  fund_category VARCHAR
                )
                """
            )
            con.execute("INSERT INTO etf_lof_reits_daily_adj VALUES ('510300.SH','20240102',1,1.1,0.9,1.05,1000,10000,1,'沪深300ETF','SH','ETF')")
            con.close()
            con = duckdb.connect(str(basic_path))
            con.execute(
                """
                CREATE TABLE etf_lof_reits_basic_export(
                  ts_code VARCHAR,
                  name VARCHAR,
                  index_code VARCHAR,
                  index_name VARCHAR,
                  list_date VARCHAR,
                  fund_category VARCHAR
                )
                """
            )
            con.execute("INSERT INTO etf_lof_reits_basic_export VALUES ('510300.SH','沪深300ETF','000300.SH','沪深300','20120528','ETF')")
            con.close()

            source = DuckDBFundDataSource(daily_path, basic_path)
            bars = source.get_daily_bars("510300.SH", "2024-01-02", "2024-01-02")
            matches = source.find_funds(keyword="沪深300")

            self.assertEqual(bars.attrs["source"], "fund_duckdb")
            self.assertEqual(float(bars.iloc[0]["close"]), 1.05)
            self.assertEqual(matches.iloc[0]["ts_code"], "510300.SH")


if __name__ == "__main__":
    unittest.main()
