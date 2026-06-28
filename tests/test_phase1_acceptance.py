"""
Phase 1 验收测试

这些用例只验证数据可信与回测可信，不引入因子、组合构建或自动下单能力。
"""

import inspect
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest.engine as engine_module
from backtest.analysis import PerformanceAnalyzer
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.execution_model import ExecutionModel
from backtest.strategy import BaseStrategy


class OneShotSignalStrategy(BaseStrategy):
    """测试用策略，只在第一次可见数据时发出固定信号。"""

    def __init__(self, symbol: str, signal: int):
        super().__init__(name="OneShotSignal")
        self.symbol = symbol
        self.signal = signal
        self.sent = False

    def generate_signals(self, data, date):
        if self.sent:
            return {}
        self.sent = True
        return {self.symbol: self.signal}


def make_manager(bars: pd.DataFrame) -> DataManager:
    """构造只包含一只股票的 DataManager。"""
    manager = DataManager()
    manager.load_data("AAA.SZ", bars)
    return manager


class TestPhase1Acceptance(unittest.TestCase):
    """逐项验收 Phase 1 的关键行为。"""

    def test_01_signal_on_t_executes_only_on_t_plus_one(self):
        """T日产生信号，只能在T+1交易日成交。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-03", "2023-01-04"]),
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.5, 10.5],
                "close": [10.2, 11.2],
                "volume": [1000, 1000],
            }
        )
        engine = BacktestEngine(make_manager(bars), OneShotSignalStrategy("AAA.SZ", 100), commission_rate=0, slippage=0)

        engine.run()

        self.assertEqual(engine.trades[0]["signal_date"], pd.Timestamp("2023-01-03"))
        self.assertEqual(engine.trades[0]["date"], pd.Timestamp("2023-01-04"))
        self.assertEqual(engine.trades[0]["price"], 11.0)

    def test_02_non_trading_t_plus_one_rolls_to_next_trading_day(self):
        """如果T+1不是交易日，应顺延到下一个交易日。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-06", "2023-01-09"]),
                "open": [10.0, 12.0],
                "high": [10.5, 12.5],
                "low": [9.5, 11.5],
                "close": [10.2, 12.2],
                "volume": [1000, 1000],
            }
        )
        engine = BacktestEngine(make_manager(bars), OneShotSignalStrategy("AAA.SZ", 100), commission_rate=0, slippage=0)

        engine.run()

        self.assertEqual(engine.trades[0]["signal_date"], pd.Timestamp("2023-01-06"))
        self.assertEqual(engine.trades[0]["date"], pd.Timestamp("2023-01-09"))

    def test_03_suspended_execution_day_does_not_trade(self):
        """成交日停牌时不成交。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-03", "2023-01-04"]),
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.5, 10.5],
                "close": [10.2, 11.2],
                "volume": [1000, 0],
                "is_suspended": [False, True],
            }
        )
        engine = BacktestEngine(make_manager(bars), OneShotSignalStrategy("AAA.SZ", 100), commission_rate=0, slippage=0)

        engine.run()

        self.assertEqual(engine.trades, [])
        self.assertEqual(engine.failed_trades[0]["reason"], "suspended")

    def test_04_limit_up_buy_does_not_trade(self):
        """买入时涨停应不成交。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-03", "2023-01-04"]),
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.5, 10.5],
                "close": [10.2, 11.2],
                "volume": [1000, 1000],
                "limit_up": [False, True],
            }
        )
        engine = BacktestEngine(make_manager(bars), OneShotSignalStrategy("AAA.SZ", 100), commission_rate=0, slippage=0)

        engine.run()

        self.assertEqual(engine.trades, [])
        self.assertEqual(engine.failed_trades[0]["reason"], "limit_up")

    def test_05_limit_down_sell_does_not_trade(self):
        """卖出时跌停应不成交。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-03", "2023-01-04"]),
                "open": [10.0, 9.0],
                "high": [10.5, 9.5],
                "low": [9.5, 8.5],
                "close": [10.2, 9.2],
                "volume": [1000, 1000],
                "limit_down": [False, True],
            }
        )
        engine = BacktestEngine(make_manager(bars), OneShotSignalStrategy("AAA.SZ", -100), commission_rate=0, slippage=0)
        engine.portfolio.positions["AAA.SZ"] = 100

        engine.run()

        self.assertEqual(engine.trades, [])
        self.assertEqual(engine.failed_trades[0]["reason"], "limit_down")

    def test_06_missing_or_zero_execution_price_does_not_trade(self):
        """成交价缺失或为0时均不成交。"""
        for bad_open in [float("nan"), 0.0]:
            bars = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2023-01-03", "2023-01-04"]),
                    "open": [10.0, bad_open],
                    "high": [10.5, 11.5],
                    "low": [9.5, 10.5],
                    "close": [10.2, 11.2],
                    "volume": [1000, 1000],
                }
            )
            engine = BacktestEngine(make_manager(bars), OneShotSignalStrategy("AAA.SZ", 100), commission_rate=0, slippage=0)

            engine.run()

            self.assertEqual(engine.trades, [])
            self.assertEqual(engine.failed_trades[0]["reason"], "invalid_price")

    def test_07_buy_cost_contains_commission_and_slippage(self):
        """买入费用包含佣金和滑点。"""
        model = ExecutionModel(commission_rate=0.001, stamp_tax_rate=0.001, slippage_bps=10, min_commission=0)

        result = model.simulate_order("AAA.SZ", 100, pd.Series({"open": 10.0}), pd.Timestamp("2023-01-04"))

        self.assertAlmostEqual(result.commission, 1.001)
        self.assertAlmostEqual(result.slippage_cost, 1.0)
        self.assertAlmostEqual(result.stamp_tax, 0.0)
        self.assertAlmostEqual(result.total_fee, 2.001)

    def test_08_sell_cost_contains_commission_stamp_tax_and_slippage(self):
        """卖出费用包含佣金、印花税和滑点。"""
        model = ExecutionModel(commission_rate=0.001, stamp_tax_rate=0.001, slippage_bps=10, min_commission=0)

        result = model.simulate_order("AAA.SZ", -100, pd.Series({"open": 10.0}), pd.Timestamp("2023-01-04"))

        self.assertAlmostEqual(result.commission, 0.999)
        self.assertAlmostEqual(result.stamp_tax, 0.999)
        self.assertAlmostEqual(result.slippage_cost, 1.0)
        self.assertAlmostEqual(result.total_fee, 2.998)

    def test_09_engine_has_no_scattered_fee_formula(self):
        """engine.py 不应再散落手续费公式，应委托 ExecutionModel。"""
        source = inspect.getsource(engine_module)

        forbidden_fragments = [
            " * self.commission_rate",
            " * self.execution_model.stamp_tax_rate",
            " * 0.001",
            " * 0.00002",
        ]
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)

    def test_10_report_summary_outputs_total_cost_and_failed_trade_count(self):
        """回测绩效摘要应输出总交易成本和成交失败次数。"""
        daily_values = pd.DataFrame(
            {
                "total_value": [100000.0, 100500.0],
                "cash": [100000.0, 99000.0],
                "positions_value": [0.0, 1500.0],
                "failed_trade_count": [0, 2],
            },
            index=pd.to_datetime(["2023-01-03", "2023-01-04"]),
        )
        trades = [
            {"quantity": 100, "price": 10.0, "total_fee": 8.0},
            {"quantity": -100, "price": 11.0, "total_fee": 9.0},
        ]

        summary = PerformanceAnalyzer(daily_values, trades, 100000.0).get_summary()

        self.assertIn("总交易成本", summary)
        self.assertIn("成交失败次数", summary)
        self.assertAlmostEqual(summary["总交易成本"], 17.0)
        self.assertEqual(summary["成交失败次数"], 2)


if __name__ == "__main__":
    unittest.main()
