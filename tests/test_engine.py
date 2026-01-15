"""
测试回测引擎模块
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data import DataManager
from backtest.strategies import BuyAndHoldStrategy, MovingAverageCrossStrategy
from backtest.engine import BacktestEngine, Order, Portfolio


class TestOrder(unittest.TestCase):
    """测试Order类"""
    
    def test_order_creation(self):
        """测试订单创建"""
        order = Order('000001.SZ', 100, 10.0, datetime(2023, 1, 1))
        
        self.assertEqual(order.symbol, '000001.SZ')
        self.assertEqual(order.quantity, 100)
        self.assertEqual(order.price, 10.0)
        self.assertFalse(order.filled)


class TestPortfolio(unittest.TestCase):
    """测试Portfolio类"""
    
    def setUp(self):
        """设置测试数据"""
        self.portfolio = Portfolio(initial_capital=1000000.0)
        
    def test_initial_state(self):
        """测试初始状态"""
        self.assertEqual(self.portfolio.cash, 1000000.0)
        self.assertEqual(len(self.portfolio.positions), 0)
        
    def test_buy_position(self):
        """测试买入"""
        success = self.portfolio.update_position('000001.SZ', 100, 10.0, 5.0)
        
        self.assertTrue(success)
        self.assertEqual(self.portfolio.positions['000001.SZ'], 100)
        self.assertEqual(self.portfolio.cash, 1000000.0 - 100 * 10.0 - 5.0)
        
    def test_sell_position(self):
        """测试卖出"""
        # 先买入
        self.portfolio.update_position('000001.SZ', 100, 10.0, 5.0)
        
        # 再卖出
        success = self.portfolio.update_position('000001.SZ', -100, 11.0, 5.0)
        
        self.assertTrue(success)
        self.assertNotIn('000001.SZ', self.portfolio.positions)
        
    def test_insufficient_cash(self):
        """测试资金不足"""
        success = self.portfolio.update_position('000001.SZ', 200000, 10.0, 0)
        
        self.assertFalse(success)
        
    def test_insufficient_position(self):
        """测试持仓不足"""
        success = self.portfolio.update_position('000001.SZ', -100, 10.0, 0)
        
        self.assertFalse(success)
        
    def test_get_total_value(self):
        """测试计算总资产"""
        self.portfolio.update_position('000001.SZ', 100, 10.0, 5.0)
        
        prices = {'000001.SZ': 12.0}
        total_value = self.portfolio.get_total_value(prices)
        
        expected = self.portfolio.cash + 100 * 12.0
        self.assertAlmostEqual(total_value, expected)


class TestBacktestEngine(unittest.TestCase):
    """测试BacktestEngine类"""
    
    def setUp(self):
        """设置测试数据"""
        # 创建测试数据
        dates = pd.date_range(start='2023-01-01', end='2023-03-31', freq='B')
        self.test_data = pd.DataFrame({
            'date': dates,
            'open': 10.0 + np.random.randn(len(dates)) * 0.1,
            'high': 10.2 + np.random.randn(len(dates)) * 0.1,
            'low': 9.8 + np.random.randn(len(dates)) * 0.1,
            'close': 10.0 + np.random.randn(len(dates)) * 0.1,
            'volume': np.random.randint(1000000, 10000000, len(dates))
        })
        
        self.symbol = '000001.SZ'
        
        # 创建数据管理器
        self.data_manager = DataManager()
        self.data_manager.load_data(self.symbol, self.test_data)
        
    def test_engine_initialization(self):
        """测试引擎初始化"""
        strategy = BuyAndHoldStrategy(self.symbol)
        engine = BacktestEngine(
            self.data_manager,
            strategy,
            initial_capital=1000000.0
        )
        
        self.assertEqual(engine.portfolio.initial_capital, 1000000.0)
        self.assertEqual(engine.commission_rate, 0.0003)
        
    def test_calculate_commission(self):
        """测试手续费计算"""
        strategy = BuyAndHoldStrategy(self.symbol)
        engine = BacktestEngine(self.data_manager, strategy)
        
        # 买入手续费
        buy_commission = engine.calculate_commission(10.0, 1000)
        self.assertGreater(buy_commission, 0)
        
        # 卖出手续费（应该更高，因为有印花税）
        sell_commission = engine.calculate_commission(10.0, -1000)
        self.assertGreater(sell_commission, buy_commission)
        
    def test_run_backtest(self):
        """测试运行回测"""
        strategy = BuyAndHoldStrategy(self.symbol)
        engine = BacktestEngine(
            self.data_manager,
            strategy,
            initial_capital=1000000.0
        )
        
        results = engine.run()
        
        # 检查结果
        self.assertIsInstance(results, pd.DataFrame)
        self.assertGreater(len(results), 0)
        self.assertIn('total_value', results.columns)
        self.assertIn('cash', results.columns)
        
    def test_ma_strategy_backtest(self):
        """测试双均线策略回测"""
        strategy = MovingAverageCrossStrategy(self.symbol, 5, 10)
        engine = BacktestEngine(
            self.data_manager,
            strategy,
            initial_capital=1000000.0
        )
        
        results = engine.run()
        
        # 检查结果
        self.assertIsInstance(results, pd.DataFrame)
        self.assertGreater(len(results), 0)
        
        # 检查交易记录
        self.assertIsInstance(engine.trades, list)


if __name__ == '__main__':
    unittest.main()
