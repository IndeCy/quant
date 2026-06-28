"""
测试策略模块
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.strategies import (
    BuyAndHoldStrategy, 
    MovingAverageCrossStrategy,
    MomentumStrategy,
    MeanReversionStrategy,
    DonchianChannelBreakoutStrategy,
    TurtleTradingStrategy,
    RSIStrategy,
    BollingerBandStrategy,
)


class TestStrategies(unittest.TestCase):
    """测试策略类"""
    
    def setUp(self):
        """设置测试数据"""
        dates = pd.date_range(start='2023-01-01', end='2023-02-01', freq='D')
        self.test_data = pd.DataFrame({
            'open': 100 + np.random.randn(len(dates)).cumsum(),
            'high': 101 + np.random.randn(len(dates)).cumsum(),
            'low': 99 + np.random.randn(len(dates)).cumsum(),
            'close': 100 + np.random.randn(len(dates)).cumsum(),
            'volume': np.random.randint(1000000, 10000000, len(dates))
        }, index=dates)
        
        self.symbol = '000001.SZ'
        
    def test_buy_and_hold_strategy(self):
        """测试买入持有策略"""
        strategy = BuyAndHoldStrategy(self.symbol)
        
        data_dict = {self.symbol: self.test_data}
        signals = strategy.generate_signals(data_dict, datetime(2023, 1, 1))
        
        self.assertIn(self.symbol, signals)
        self.assertGreater(signals[self.symbol], 0)
        
        # 第二次调用不应该再生成信号
        signals2 = strategy.generate_signals(data_dict, datetime(2023, 1, 2))
        self.assertEqual(len(signals2), 0)
        
    def test_ma_cross_strategy(self):
        """测试双均线策略"""
        strategy = MovingAverageCrossStrategy(self.symbol, short_window=5, long_window=10)
        
        data_dict = {self.symbol: self.test_data}
        signals = strategy.generate_signals(data_dict, datetime(2023, 1, 20))
        
        self.assertIsInstance(signals, dict)
        self.assertEqual(strategy.parameters["strategy_type"], "趋势跟随")
        
    def test_momentum_strategy(self):
        """测试动量策略"""
        strategy = MomentumStrategy(self.symbol, lookback_period=10)
        
        data_dict = {self.symbol: self.test_data}
        signals = strategy.generate_signals(data_dict, datetime(2023, 1, 20))
        
        self.assertIsInstance(signals, dict)
        
    def test_mean_reversion_strategy(self):
        """测试均值回归策略"""
        strategy = MeanReversionStrategy(self.symbol, window=10)
        
        data_dict = {self.symbol: self.test_data}
        signals = strategy.generate_signals(data_dict, datetime(2023, 1, 20))
        
        self.assertIsInstance(signals, dict)

    def test_donchian_channel_breakout_buys_on_high_breakout(self):
        """唐奇安通道突破策略在突破前N日高点时应买入"""
        dates = pd.date_range(start='2023-01-01', periods=6, freq='D')
        data = pd.DataFrame({
            'open': [10, 10, 10, 10, 10, 10],
            'high': [10, 11, 12, 13, 14, 16],
            'low': [9, 9, 9, 9, 9, 9],
            'close': [10, 11, 12, 13, 14, 16],
            'volume': [1000] * 6,
        }, index=dates)
        strategy = DonchianChannelBreakoutStrategy(self.symbol, entry_window=5, exit_window=3)

        signals = strategy.generate_signals({self.symbol: data}, dates[-1])

        self.assertEqual(signals, {self.symbol: 1000000})

    def test_donchian_channel_breakout_sells_on_low_breakdown(self):
        """唐奇安通道突破策略在跌破前N日低点时应卖出"""
        dates = pd.date_range(start='2023-01-01', periods=6, freq='D')
        data = pd.DataFrame({
            'open': [20, 20, 20, 20, 20, 20],
            'high': [21, 21, 21, 21, 21, 21],
            'low': [18, 17, 16, 15, 14, 12],
            'close': [18, 17, 16, 15, 14, 12],
            'volume': [1000] * 6,
        }, index=dates)
        strategy = DonchianChannelBreakoutStrategy(self.symbol, entry_window=5, exit_window=3)

        signals = strategy.generate_signals({self.symbol: data}, dates[-1])

        self.assertEqual(signals, {self.symbol: -1000000})

    def test_turtle_trading_buys_on_entry_breakout(self):
        """海龟策略在突破入场窗口高点时应买入"""
        dates = pd.date_range(start='2023-01-01', periods=8, freq='D')
        data = pd.DataFrame({
            'open': [10, 11, 12, 13, 14, 15, 16, 20],
            'high': [11, 12, 13, 14, 15, 16, 17, 21],
            'low': [9, 10, 11, 12, 13, 14, 15, 19],
            'close': [10, 11, 12, 13, 14, 15, 16, 20],
            'volume': [1000] * 8,
        }, index=dates)
        strategy = TurtleTradingStrategy(self.symbol, entry_window=5, exit_window=3, atr_window=3)

        signals = strategy.generate_signals({self.symbol: data}, dates[-1])

        self.assertEqual(signals, {self.symbol: 1000000})

    def test_rsi_strategy_buys_when_oversold(self):
        """RSI策略在超卖时应买入"""
        dates = pd.date_range(start='2023-01-01', periods=8, freq='D')
        data = pd.DataFrame({
            'open': [20, 19, 18, 17, 16, 15, 14, 13],
            'high': [21, 20, 19, 18, 17, 16, 15, 14],
            'low': [19, 18, 17, 16, 15, 14, 13, 12],
            'close': [20, 19, 18, 17, 16, 15, 14, 13],
            'volume': [1000] * 8,
        }, index=dates)
        strategy = RSIStrategy(self.symbol, window=5, oversold=30, overbought=70)

        signals = strategy.generate_signals({self.symbol: data}, dates[-1])

        self.assertEqual(signals, {self.symbol: 1000000})

    def test_bollinger_breakout_strategy_buys_above_upper_band(self):
        """布林带突破策略在价格突破上轨时应买入"""
        dates = pd.date_range(start='2023-01-01', periods=8, freq='D')
        data = pd.DataFrame({
            'open': [10, 10, 10, 10, 10, 10, 10, 15],
            'high': [10, 10, 10, 10, 10, 10, 10, 15],
            'low': [10, 10, 10, 10, 10, 10, 10, 15],
            'close': [10, 10, 10, 10, 10, 10, 10, 15],
            'volume': [1000] * 8,
        }, index=dates)
        strategy = BollingerBandStrategy(self.symbol, window=5, num_std=1.0, mode="breakout")

        signals = strategy.generate_signals({self.symbol: data}, dates[-1])

        self.assertEqual(signals, {self.symbol: 1000000})


if __name__ == '__main__':
    unittest.main()
