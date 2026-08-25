"""
Phase 1 数据可信与回测可信测试
"""

import math
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.strategy import BaseStrategy
from backtest.execution_model import ExecutionModel
from data.calendar import TradingCalendar


class OneShotBuyStrategy(BaseStrategy):
    """测试用单次买入策略，在第一个可见交易日发出买入信号。"""

    def __init__(self, symbol: str, quantity: int = 100):
        super().__init__(name="OneShotBuy")
        self.symbol = symbol
        self.quantity = quantity
        self.sent = False

    def generate_signals(self, data, date):
        if self.sent:
            return {}
        self.sent = True
        return {self.symbol: self.quantity}


class TestPhase1TrustworthyBacktest(unittest.TestCase):
    """验证 Phase 1 的交易日历、成交模型和回测接入。"""

    def _load_bars(self, bars: pd.DataFrame) -> DataManager:
        manager = DataManager()
        manager.load_data("AAA.SZ", bars)
        return manager

    def test_calendar_skips_non_trading_day(self):
        """交易日历应跳过周末，返回下一个交易日。"""
        calendar = TradingCalendar()

        self.assertFalse(calendar.is_trading_day(pd.Timestamp("2023-01-07")))
        self.assertEqual(calendar.next_trading_day(pd.Timestamp("2023-01-06")), pd.Timestamp("2023-01-09"))
        self.assertEqual(
            calendar.trading_days("2023-01-06", "2023-01-10"),
            [pd.Timestamp("2023-01-06"), pd.Timestamp("2023-01-09"), pd.Timestamp("2023-01-10")],
        )

    def test_signal_on_t_executes_on_next_trading_day(self):
        """默认不允许当日信号当日成交，应在下一个交易日按开盘价成交。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-06", "2023-01-09"]),
                "open": [10.0, 12.0],
                "high": [10.5, 12.5],
                "low": [9.8, 11.8],
                "close": [10.0, 12.2],
                "volume": [1000, 1000],
            }
        )
        engine = BacktestEngine(
            self._load_bars(bars),
            OneShotBuyStrategy("AAA.SZ", 100),
            initial_capital=100000.0,
            commission_rate=0.0,
            slippage=0.0,
        )

        engine.run()

        self.assertEqual(len(engine.trades), 1)
        self.assertEqual(engine.trades[0]["signal_date"], pd.Timestamp("2023-01-06"))
        self.assertEqual(engine.trades[0]["date"], pd.Timestamp("2023-01-09"))
        self.assertEqual(engine.trades[0]["price"], 12.0)

    def test_same_day_execution_is_not_default(self):
        """只有一个交易日时默认无法成交，证明同日成交不再是默认行为。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-06"]),
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.0],
                "volume": [1000],
            }
        )
        engine = BacktestEngine(
            self._load_bars(bars),
            OneShotBuyStrategy("AAA.SZ", 100),
            initial_capital=100000.0,
            commission_rate=0.0,
            slippage=0.0,
        )

        engine.run()

        self.assertEqual(engine.trades, [])

    def test_suspended_execution_day_does_not_trade(self):
        """成交日停牌时应拦截订单，不产生实际成交。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-06", "2023-01-09"]),
                "open": [10.0, 12.0],
                "high": [10.5, 12.5],
                "low": [9.8, 11.8],
                "close": [10.0, 12.2],
                "volume": [1000, 0],
                "is_suspended": [False, True],
            }
        )
        engine = BacktestEngine(
            self._load_bars(bars),
            OneShotBuyStrategy("AAA.SZ", 100),
            initial_capital=100000.0,
            commission_rate=0.0,
            slippage=0.0,
        )

        engine.run()

        self.assertEqual(engine.trades, [])
        self.assertEqual(engine.failed_trade_count, 1)

    def test_missing_execution_price_does_not_trade(self):
        """成交价缺失时应拦截订单，避免用无效价格更新持仓。"""
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-06", "2023-01-09"]),
                "open": [10.0, math.nan],
                "high": [10.5, 12.5],
                "low": [9.8, 11.8],
                "close": [10.0, 12.2],
                "volume": [1000, 1000],
            }
        )
        engine = BacktestEngine(
            self._load_bars(bars),
            OneShotBuyStrategy("AAA.SZ", 100),
            initial_capital=100000.0,
            commission_rate=0.0,
            slippage=0.0,
        )

        engine.run()

        self.assertEqual(engine.trades, [])
        self.assertEqual(engine.failed_trade_count, 1)

    def test_buy_cost_contains_commission_and_slippage(self):
        """买入费用应包含佣金和滑点成本。"""
        model = ExecutionModel(commission_rate=0.001, stamp_tax_rate=0.001, slippage_bps=10, min_commission=0.0)

        result = model.simulate_order("AAA.SZ", 100, pd.Series({"open": 10.0}), pd.Timestamp("2023-01-09"))

        self.assertTrue(result.success)
        self.assertAlmostEqual(result.price, 10.01)
        self.assertAlmostEqual(result.commission, 1.001)
        self.assertAlmostEqual(result.slippage_cost, 1.0)
        self.assertAlmostEqual(result.total_fee, 2.001)

    def test_sell_cost_contains_commission_stamp_tax_and_slippage(self):
        """卖出费用应包含佣金、印花税和滑点成本。"""
        model = ExecutionModel(commission_rate=0.001, stamp_tax_rate=0.001, slippage_bps=10, min_commission=0.0)

        result = model.simulate_order("AAA.SZ", -100, pd.Series({"open": 10.0}), pd.Timestamp("2023-01-09"))

        self.assertTrue(result.success)
        self.assertAlmostEqual(result.price, 9.99)
        self.assertAlmostEqual(result.commission, 0.999)
        self.assertAlmostEqual(result.stamp_tax, 0.999)
        self.assertAlmostEqual(result.slippage_cost, 1.0)
        self.assertAlmostEqual(result.total_fee, 2.998)


if __name__ == "__main__":
    unittest.main()
