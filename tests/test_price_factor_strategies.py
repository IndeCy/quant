"""
Milestone 1.1 纯价格因子策略测试。
"""

import unittest

import pandas as pd

from backtest.price_factor_strategies import PriceFactorRotationStrategy


def make_bars(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=dates,
    )


class TestPriceFactorRotationStrategy(unittest.TestCase):
    """验证纯价格因子策略定义。"""

    def test_momentum_selects_highest_skip_recent_return(self):
        strategy = PriceFactorRotationStrategy(
            ["A", "B", "C"],
            mode="momentum",
            top_n=2,
            momentum_lookback=4,
            skip_recent=1,
        )
        data = {
            "A": make_bars([10, 11, 12, 12, 12]),
            "B": make_bars([10, 10, 10, 15, 9]),
            "C": make_bars([10, 10, 11, 11, 11]),
        }

        signals = strategy.generate_signals(data, pd.Timestamp("2024-01-08"))

        self.assertEqual(signals["A"], 0.5)
        self.assertEqual(signals["B"], 0.5)
        self.assertEqual(signals["C"], 0.0)

    def test_low_volatility_selects_lowest_std(self):
        strategy = PriceFactorRotationStrategy(
            ["A", "B"],
            mode="low_volatility",
            top_n=1,
            volatility_lookback=4,
        )
        data = {
            "A": make_bars([10, 10.1, 10.0, 10.1, 10.0]),
            "B": make_bars([10, 12, 9, 13, 8]),
        }

        signals = strategy.generate_signals(data, pd.Timestamp("2024-01-08"))

        self.assertEqual(signals["A"], 1.0)
        self.assertEqual(signals["B"], 0.0)

    def test_trend_following_filters_below_ma60(self):
        strong = list(range(1, 71))
        weak = list(range(70, 0, -1))
        strategy = PriceFactorRotationStrategy(
            ["STRONG", "WEAK"],
            mode="trend_following",
            top_n=1,
            momentum_lookback=4,
            skip_recent=1,
            trend_short_window=20,
            trend_long_window=60,
        )

        signals = strategy.generate_signals(
            {"STRONG": make_bars(strong), "WEAK": make_bars(weak)},
            pd.Timestamp("2024-04-08"),
        )

        self.assertEqual(signals["STRONG"], 1.0)
        self.assertEqual(signals["WEAK"], 0.0)

    def test_rebalances_only_once_per_month(self):
        strategy = PriceFactorRotationStrategy(["A"], mode="momentum", top_n=1, momentum_lookback=2, skip_recent=1)
        data = {"A": make_bars([10, 11, 12])}

        first = strategy.generate_signals(data, pd.Timestamp("2024-01-03"))
        second = strategy.generate_signals(data, pd.Timestamp("2024-01-04"))
        third = strategy.generate_signals(data, pd.Timestamp("2024-02-01"))

        self.assertEqual(first["A"], 1.0)
        self.assertEqual(second, {})
        self.assertEqual(third["A"], 1.0)


if __name__ == "__main__":
    unittest.main()
