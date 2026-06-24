"""
策略对比研究脚本的轻量单测。
"""

from __future__ import annotations

import unittest

import duckdb
import pandas as pd

from examples.strategy_comparison_research import (
    BacktestResearchResult,
    build_annual_returns,
    calculate_metrics,
    create_feature_table,
    load_monthly_selections,
    mark_to_market,
)


class TestStrategyComparisonResearch(unittest.TestCase):
    """验证研究脚本的可复用指标计算。"""

    def test_calculate_metrics_outputs_required_fields(self):
        values = pd.Series(
            [100.0, 105.0, 102.0, 110.0],
            index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        )

        metrics = calculate_metrics(values)

        self.assertEqual(set(metrics), {"total_return", "annual_return", "max_drawdown", "sharpe"})
        self.assertGreater(metrics["total_return"], 0)
        self.assertLess(metrics["max_drawdown"], 0)

    def test_build_annual_returns_uses_calendar_year(self):
        values = pd.Series(
            [100.0, 110.0, 121.0, 108.9],
            index=pd.to_datetime(["2024-01-02", "2024-12-31", "2025-01-02", "2025-12-31"]),
        )
        result = BacktestResearchResult("测试策略", values, [], [], 0.0, 0.0)

        annual = build_annual_returns({"测试策略": result})

        self.assertEqual(list(annual["年份"]), [2024, 2025])
        self.assertAlmostEqual(float(annual.loc[annual["年份"] == 2024, "年度收益"].iloc[0]), 0.10)
        self.assertAlmostEqual(float(annual.loc[annual["年份"] == 2025, "年度收益"].iloc[0]), -0.10)

    def test_mark_to_market_carries_last_close_for_suspended_holding(self):
        index = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-02"), "AAA")],
            names=["date", "symbol"],
        )
        bars = pd.DataFrame({"close": [10.0]}, index=index)

        value = mark_to_market({"AAA": 100}, bars, pd.Timestamp("2024-01-03"))

        self.assertEqual(value, 1000.0)

    def test_feature_table_keeps_suspended_rows_but_excludes_them_from_selection(self):
        con = duckdb.connect(":memory:")
        try:
            con.execute(
                """
                CREATE TABLE daily_adj_cache(
                    ts_code VARCHAR,
                    trade_date VARCHAR,
                    open_qfq DOUBLE,
                    high_qfq DOUBLE,
                    low_qfq DOUBLE,
                    close_qfq DOUBLE,
                    pre_close_qfq DOUBLE
                )
                """
            )
            con.execute(
                """
                CREATE TABLE daily(
                    ts_code VARCHAR,
                    trade_date VARCHAR,
                    vol DOUBLE,
                    amount DOUBLE
                )
                """
            )
            con.execute("CREATE TABLE stock_st(ts_code VARCHAR, trade_date VARCHAR, name VARCHAR)")
            con.execute(
                """
                INSERT INTO daily_adj_cache VALUES
                ('AAA.SZ','20250102',10,10,10,10,9),
                ('AAA.SZ','20250103',10,10,10,10,10),
                ('BBB.SZ','20250103',11,11,11,11,10)
                """
            )
            con.execute(
                """
                INSERT INTO daily VALUES
                ('AAA.SZ','20250102',100,1000),
                ('AAA.SZ','20250103',0,0),
                ('BBB.SZ','20250103',200,3000)
                """
            )

            create_feature_table(con)

            feature_rows = con.execute(
                """
                SELECT symbol, trade_date, volume, amount, is_suspended
                FROM features
                WHERE trade_date = '20250103'
                ORDER BY symbol
                """
            ).fetchall()
            selections = load_monthly_selections(
                con,
                ["20250103"],
                "ret20 IS NULL ORDER BY symbol ASC LIMIT 20",
            )
        finally:
            con.close()

        self.assertEqual(
            feature_rows,
            [
                ("AAA.SZ", "20250103", 0.0, 0.0, True),
                ("BBB.SZ", "20250103", 200.0, 3000.0, False),
            ],
        )
        self.assertEqual(selections["20250103"], ["BBB.SZ"])


if __name__ == "__main__":
    unittest.main()
