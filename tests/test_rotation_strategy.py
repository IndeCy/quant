"""
测试行业动量轮动策略
"""

import unittest

import pandas as pd

from backtest.rotation import IndustryMomentumRotationStrategy


def make_bars(closes: list[float]) -> pd.DataFrame:
    """根据收盘价生成最小 K 线数据"""
    dates = pd.date_range(start="2023-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [price + 1 for price in closes],
            "low": [price - 1 for price in closes],
            "close": closes,
            "volume": [1000000] * len(closes),
        },
        index=dates,
    )


class TestIndustryMomentumRotationStrategy(unittest.TestCase):
    """测试行业轮动信号生成"""

    def test_selects_top_momentum_industries_on_first_rebalance(self):
        """首次调仓应买入过去收益最高的 Top N 行业"""
        strategy = IndustryMomentumRotationStrategy(
            symbols=["电力", "半导体", "银行"],
            lookback_period=3,
            top_n=2,
            rebalance_frequency=5,
        )
        data = {
            "电力": make_bars([10, 11, 12, 13]),
            "半导体": make_bars([10, 10, 11, 15]),
            "银行": make_bars([10, 10, 10, 10.5]),
        }

        signals = strategy.generate_signals(data, data["电力"].index[-1])

        self.assertEqual(signals, {"半导体": 1000000, "电力": 1000000})
        self.assertEqual(strategy.current_holdings, {"半导体", "电力"})

    def test_sells_dropped_industry_and_buys_new_top_industry(self):
        """下一次调仓应卖出掉出 Top N 的行业并买入新强势行业"""
        strategy = IndustryMomentumRotationStrategy(
            symbols=["电力", "半导体", "银行"],
            lookback_period=3,
            top_n=2,
            rebalance_frequency=1,
        )
        first_data = {
            "电力": make_bars([10, 11, 12, 13]),
            "半导体": make_bars([10, 10, 11, 15]),
            "银行": make_bars([10, 10, 10, 10.5]),
        }
        strategy.generate_signals(first_data, first_data["电力"].index[-1])
        second_data = {
            "电力": make_bars([10, 11, 12, 13, 13.5]),
            "半导体": make_bars([10, 10, 11, 15, 14]),
            "银行": make_bars([10, 10, 10, 10.5, 16]),
        }

        signals = strategy.generate_signals(second_data, second_data["电力"].index[-1])

        self.assertEqual(signals, {"电力": -1000000, "银行": 1000000})
        self.assertEqual(strategy.current_holdings, {"银行", "半导体"})

    def test_market_filter_sells_all_when_market_below_moving_average(self):
        """市场过滤开启时，基准跌破均线应清仓行业持仓"""
        strategy = IndustryMomentumRotationStrategy(
            symbols=["电力", "半导体"],
            lookback_period=3,
            top_n=1,
            rebalance_frequency=1,
            market_filter_symbol="上证指数",
            market_ma_window=3,
        )
        first_data = {
            "电力": make_bars([10, 11, 12, 13]),
            "半导体": make_bars([10, 10, 10, 10.5]),
            "上证指数": make_bars([10, 11, 12, 13]),
        }
        strategy.generate_signals(first_data, first_data["电力"].index[-1])
        second_data = {
            "电力": make_bars([10, 11, 12, 13, 13.5]),
            "半导体": make_bars([10, 10, 10, 10.5, 11]),
            "上证指数": make_bars([10, 11, 12, 13, 8]),
        }

        signals = strategy.generate_signals(second_data, second_data["电力"].index[-1])

        self.assertEqual(signals, {"电力": -1000000})
        self.assertEqual(strategy.current_holdings, set())

    def test_can_return_equal_target_weights_for_top_industries(self):
        """开启目标权重模式时，Top N 行业应返回等权仓位"""
        strategy = IndustryMomentumRotationStrategy(
            symbols=["电力", "半导体", "银行"],
            lookback_period=3,
            top_n=2,
            rebalance_frequency=5,
            use_target_weight=True,
        )
        data = {
            "电力": make_bars([10, 11, 12, 13]),
            "半导体": make_bars([10, 10, 11, 15]),
            "银行": make_bars([10, 10, 10, 10.5]),
        }

        signals = strategy.generate_signals(data, data["电力"].index[-1])

        self.assertEqual(signals, {"半导体": 0.5, "电力": 0.5, "银行": 0.0})

    def test_industry_trend_filter_excludes_symbol_below_moving_average(self):
        """行业自身跌破趋势均线时，不应进入轮动目标持仓"""
        strategy = IndustryMomentumRotationStrategy(
            symbols=["电力", "半导体", "银行"],
            lookback_period=3,
            top_n=2,
            rebalance_frequency=5,
            industry_ma_window=3,
            use_target_weight=True,
        )
        data = {
            "电力": make_bars([10, 11, 12, 13]),
            "半导体": make_bars([10, 30, 25, 20]),
            "银行": make_bars([10, 10, 11, 12]),
        }

        signals = strategy.generate_signals(data, data["电力"].index[-1])

        self.assertEqual(signals, {"电力": 0.5, "银行": 0.5, "半导体": 0.0})

    def test_composite_momentum_prefers_multi_period_strength(self):
        """多周期动量应优先选择中长期更强的行业"""
        strategy = IndustryMomentumRotationStrategy(
            symbols=["短冲", "稳强", "弱势"],
            lookback_period=2,
            momentum_windows=[2, 5],
            top_n=1,
            rebalance_frequency=5,
            use_target_weight=True,
        )
        data = {
            "短冲": make_bars([10, 10, 10, 10, 10, 13]),
            "稳强": make_bars([10, 11, 12, 13, 14, 15]),
            "弱势": make_bars([10, 10, 10, 10, 10, 10.2]),
        }

        signals = strategy.generate_signals(data, data["短冲"].index[-1])

        self.assertEqual(signals, {"稳强": 1.0, "弱势": 0.0, "短冲": 0.0})

    def test_holding_buffer_keeps_existing_position_within_buffer_rank(self):
        """持仓缓冲应保留仍在缓冲排名内的原持仓，减少频繁换手"""
        strategy = IndustryMomentumRotationStrategy(
            symbols=["A", "B", "C"],
            lookback_period=2,
            top_n=1,
            rebalance_frequency=1,
            holding_buffer_rank=2,
            use_target_weight=True,
        )
        first_data = {
            "A": make_bars([10, 11, 13]),
            "B": make_bars([10, 10, 11]),
            "C": make_bars([10, 10, 10.5]),
        }
        strategy.generate_signals(first_data, first_data["A"].index[-1])
        second_data = {
            "A": make_bars([10, 11, 13, 13.5]),
            "B": make_bars([10, 10, 11, 14]),
            "C": make_bars([10, 10, 10.5, 10.8]),
        }

        signals = strategy.generate_signals(second_data, second_data["A"].index[-1])

        self.assertEqual(signals, {"A": 1.0, "B": 0.0, "C": 0.0})


if __name__ == "__main__":
    unittest.main()
