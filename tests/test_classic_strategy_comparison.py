"""
测试经典策略对比工具
"""

import unittest

import pandas as pd

from examples.compare_classic_strategies import build_classic_strategy_suite, run_strategy_comparison


class TestClassicStrategyComparison(unittest.TestCase):
    """测试经典策略批量回测能力"""

    def setUp(self):
        """构造一段趋势行情，避免依赖外部行情接口"""
        dates = pd.date_range(start="2023-01-01", periods=80, freq="D")
        close = [100 + i * 0.5 for i in range(80)]
        self.symbol = "000001.SH"
        self.bars = pd.DataFrame(
            {
                "open": close,
                "high": [price + 1 for price in close],
                "low": [price - 1 for price in close],
                "close": close,
                "volume": [1000000] * len(close),
                "amount": [100000000] * len(close),
            },
            index=dates,
        )

    def test_build_classic_strategy_suite_contains_expected_strategies(self):
        """经典策略集合应包含计划中的核心策略"""
        strategies = build_classic_strategy_suite(self.symbol)
        names = [strategy.name for strategy in strategies]

        self.assertIn("BuyAndHold", names)
        self.assertIn("MA_Cross", names)
        self.assertIn("Donchian_Channel_Breakout", names)
        self.assertIn("Turtle_Trading", names)
        self.assertIn("RSI_Reversion", names)
        self.assertIn("Bollinger_reversion", names)
        self.assertIn("Bollinger_breakout", names)

    def test_run_strategy_comparison_outputs_metrics_table(self):
        """批量回测应输出统一绩效指标表"""
        comparison = run_strategy_comparison(self.symbol, self.bars, initial_capital=1000000)

        self.assertGreaterEqual(len(comparison), 7)
        self.assertIn("策略", comparison.columns)
        self.assertIn("总收益率", comparison.columns)
        self.assertIn("最大回撤", comparison.columns)
        self.assertIn("交易次数", comparison.columns)
        self.assertIn("买入持有收益率", comparison.columns)
        self.assertIn("超额收益率", comparison.columns)


if __name__ == "__main__":
    unittest.main()
