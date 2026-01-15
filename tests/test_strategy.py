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
    MeanReversionStrategy
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


if __name__ == '__main__':
    unittest.main()
