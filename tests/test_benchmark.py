"""
测试基线收益对比模块
"""

import unittest

import pandas as pd

from backtest.benchmark import (
    build_benchmark_curve,
    calculate_return_comparison,
    calculate_yearly_return_comparison,
)


class TestBenchmark(unittest.TestCase):
    """测试策略收益和基线收益对比"""

    def setUp(self):
        """构造策略资产曲线和上证指数基线K线"""
        self.strategy_values = pd.DataFrame(
            {
                "total_value": [1_000_000.0, 1_100_000.0, 1_210_000.0, 1_331_000.0],
                "cash": [1_000_000.0, 1_100_000.0, 1_210_000.0, 1_331_000.0],
                "positions_value": [0.0, 0.0, 0.0, 0.0],
            },
            index=pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"]),
        )
        self.benchmark_bars = pd.DataFrame(
            {
                "close": [100.0, 105.0, 110.0, 121.0],
                "open": [100.0, 104.0, 106.0, 111.0],
                "high": [101.0, 106.0, 111.0, 122.0],
                "low": [99.0, 103.0, 105.0, 109.0],
                "volume": [1000.0, 1000.0, 1000.0, 1000.0],
                "amount": [0.0, 0.0, 0.0, 0.0],
            },
            index=pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"]),
        )

    def test_build_benchmark_curve_aligns_to_strategy_dates(self):
        """基线点位应按策略日期对齐成同初始资金的资产曲线"""
        curve = build_benchmark_curve(
            self.benchmark_bars,
            self.strategy_values.index,
            initial_capital=1_000_000.0,
        )

        self.assertEqual(len(curve), 4)
        self.assertAlmostEqual(curve.iloc[0], 1_000_000.0)
        self.assertAlmostEqual(curve.iloc[-1], 1_210_000.0)

    def test_calculate_return_comparison_outputs_excess_return(self):
        """收益对比应同时包含策略、基线和超额收益"""
        comparison = calculate_return_comparison(
            strategy_daily_values=self.strategy_values,
            benchmark_bars=self.benchmark_bars,
            initial_capital=1_000_000.0,
            benchmark_name="上证指数",
        )

        self.assertEqual(comparison["基线名称"], "上证指数")
        self.assertAlmostEqual(comparison["策略总收益率"], 0.331)
        self.assertAlmostEqual(comparison["基线总收益率"], 0.21)
        self.assertAlmostEqual(comparison["超额收益率"], 0.121)

    def test_calculate_yearly_return_comparison(self):
        """分年度对比应按每年首末资产计算策略和基线收益"""
        rows = calculate_yearly_return_comparison(
            strategy_daily_values=self.strategy_values,
            benchmark_bars=self.benchmark_bars,
            initial_capital=1_000_000.0,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["year"], 2025)
        self.assertAlmostEqual(rows[0]["strategy_return"], 0.10)
        self.assertAlmostEqual(rows[0]["benchmark_return"], 0.05)
        self.assertAlmostEqual(rows[0]["excess_return"], 0.05)
        self.assertEqual(rows[1]["year"], 2026)
        self.assertAlmostEqual(rows[1]["strategy_return"], 0.21)
        self.assertAlmostEqual(rows[1]["benchmark_return"], 121.0 / 105.0 - 1)


if __name__ == "__main__":
    unittest.main()
