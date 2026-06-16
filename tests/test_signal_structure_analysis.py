"""
信号与结构解耦分析测试。
"""

import unittest

import pandas as pd

from backtest.signal_structure_analysis import (
    classify_market_regimes,
    decompose_lifecycle_alpha,
    summarize_regime_returns,
)


class TestSignalStructureAnalysis(unittest.TestCase):
    """验证 alpha 拆解与市场环境统计。"""

    def test_decomposes_entry_holding_exit_alpha_from_real_trades(self):
        dates = pd.date_range("2024-01-01", periods=70, freq="D")
        prices = pd.DataFrame(
            {
                "AAA": [100 + i for i in range(70)],
                "BBB": [100 for _ in range(70)],
            },
            index=dates,
        )
        benchmark = pd.Series([100 for _ in range(70)], index=dates)
        trades = [
            {"date": "2024-01-01", "symbol": "AAA", "quantity": 100},
            {"date": "2024-02-10", "symbol": "AAA", "quantity": -100},
        ]

        result = decompose_lifecycle_alpha(trades, prices, benchmark, "2024-03-10", short_window_days=10)

        self.assertGreater(result.entry_alpha, 0)
        self.assertGreater(result.holding_alpha, 0)
        self.assertLess(result.exit_alpha, 0)
        self.assertEqual(result.sample_count, 1)

    def test_classifies_market_regimes_by_year(self):
        dates = pd.to_datetime(["2020-01-01", "2020-12-31", "2021-01-01", "2021-12-31", "2022-01-01", "2022-12-31"])
        benchmark = pd.Series([100, 120, 100, 85, 100, 105], index=dates)

        regimes = classify_market_regimes(benchmark)

        self.assertEqual(regimes.loc[2020], "bull")
        self.assertEqual(regimes.loc[2021], "bear")
        self.assertEqual(regimes.loc[2022], "sideways")

    def test_summarizes_strategy_returns_by_regime(self):
        dates = pd.to_datetime(["2020-01-01", "2020-12-31", "2021-01-01", "2021-12-31"])
        daily_values = pd.DataFrame({"total_value": [100, 110, 110, 99]}, index=dates)
        regimes = pd.Series({2020: "bull", 2021: "bear"})

        summary = summarize_regime_returns(daily_values, regimes)

        self.assertEqual(set(summary["regime"]), {"bull", "bear"})


if __name__ == "__main__":
    unittest.main()
