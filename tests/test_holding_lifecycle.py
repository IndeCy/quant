"""
持仓生命周期分析测试。
"""

import unittest

import pandas as pd

from backtest.holding_lifecycle import (
    build_holding_periods,
    holding_distribution,
    lifecycle_summary,
    rolling_retention,
    symbol_lifecycle_summary,
)


class TestHoldingLifecycle(unittest.TestCase):
    """验证生命周期基于真实成交记录重建。"""

    def test_builds_continuous_period_until_position_zero(self):
        trades = [
            {"date": "2024-01-02", "symbol": "AAA", "quantity": 100},
            {"date": "2024-01-10", "symbol": "AAA", "quantity": 100},
            {"date": "2024-02-01", "symbol": "AAA", "quantity": -200},
        ]

        periods = build_holding_periods(trades)

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0].symbol, "AAA")
        self.assertEqual(periods[0].holding_days, 30)

    def test_keeps_open_period_to_end_date(self):
        trades = [{"date": "2024-01-02", "symbol": "AAA", "quantity": 100}]

        periods = build_holding_periods(trades, end_date="2024-04-02")

        self.assertEqual(periods[0].holding_days, 91)
        self.assertTrue(periods[0].is_open)

    def test_summary_and_distribution(self):
        trades = [
            {"date": "2024-01-02", "symbol": "A", "quantity": 100},
            {"date": "2024-01-20", "symbol": "A", "quantity": -100},
            {"date": "2024-01-02", "symbol": "B", "quantity": 100},
            {"date": "2024-04-15", "symbol": "B", "quantity": -100},
        ]

        summary = lifecycle_summary(trades)
        distribution = holding_distribution(build_holding_periods(trades))

        self.assertAlmostEqual(summary["average_holding_days"], 61.0)
        self.assertAlmostEqual(summary["median_holding_days"], 61.0)
        self.assertEqual(distribution["lt_1m"], 0.5)
        self.assertEqual(distribution["m3_6"], 0.5)

    def test_rolling_retention_uses_actual_positions(self):
        trades = [
            {"date": "2024-01-02", "symbol": "A", "quantity": 100},
            {"date": "2024-01-02", "symbol": "B", "quantity": 100},
            {"date": "2024-02-02", "symbol": "A", "quantity": -100},
            {"date": "2024-02-02", "symbol": "C", "quantity": 100},
        ]

        retention = rolling_retention(trades, "2024-01-01", "2024-03-31")

        self.assertAlmostEqual(float(retention.iloc[0]), 0.5)
        self.assertAlmostEqual(float(retention.iloc[1]), 1.0)

    def test_symbol_lifecycle_summary_orders_longest_average(self):
        trades = [
            {"date": "2024-01-02", "symbol": "A", "quantity": 100},
            {"date": "2024-01-20", "symbol": "A", "quantity": -100},
            {"date": "2024-01-02", "symbol": "B", "quantity": 100},
            {"date": "2024-04-15", "symbol": "B", "quantity": -100},
        ]

        result = symbol_lifecycle_summary(build_holding_periods(trades))

        self.assertEqual(result.iloc[0]["symbol"], "B")
        self.assertGreater(result.iloc[0]["average_holding_days"], result.iloc[1]["average_holding_days"])


if __name__ == "__main__":
    unittest.main()
