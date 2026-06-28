"""
测试数据管理模块
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data import DataManager


class TestDataManager(unittest.TestCase):
    """测试DataManager类"""
    
    def setUp(self):
        """设置测试数据"""
        self.data_manager = DataManager()
        
        # 创建测试数据
        dates = pd.date_range(start='2023-01-01', end='2023-01-10', freq='D')
        self.test_data = pd.DataFrame({
            'date': dates,
            'open': np.arange(100, 110),
            'high': np.arange(101, 111),
            'low': np.arange(99, 109),
            'close': np.arange(100.5, 110.5),
            'volume': np.random.randint(1000000, 10000000, len(dates))
        })
        
    def test_load_data(self):
        """测试加载数据"""
        symbol = '000001.SZ'
        self.data_manager.load_data(symbol, self.test_data)
        
        self.assertIn(symbol, self.data_manager.data)
        self.assertEqual(len(self.data_manager.data[symbol]), len(self.test_data))
        
    def test_get_data(self):
        """测试获取数据"""
        symbol = '000001.SZ'
        self.data_manager.load_data(symbol, self.test_data)
        
        data = self.data_manager.get_data(symbol)
        self.assertIsInstance(data, pd.DataFrame)
        self.assertEqual(len(data), len(self.test_data))
        
    def test_get_data_with_date_range(self):
        """测试带日期范围的数据获取"""
        symbol = '000001.SZ'
        self.data_manager.load_data(symbol, self.test_data)
        
        start_date = datetime(2023, 1, 3)
        end_date = datetime(2023, 1, 7)
        
        data = self.data_manager.get_data(symbol, start_date, end_date)
        self.assertGreaterEqual(len(data), 1)
        self.assertTrue(all(data.index >= start_date))
        self.assertTrue(all(data.index <= end_date))
        
    def test_get_price(self):
        """测试获取特定日期价格"""
        symbol = '000001.SZ'
        self.data_manager.load_data(symbol, self.test_data)
        
        date = pd.Timestamp('2023-01-05')
        price = self.data_manager.get_price(symbol, date, 'close')
        
        self.assertIsInstance(price, (float, np.floating))
        self.assertGreater(price, 0)
        
    def test_get_symbols(self):
        """测试获取所有股票代码"""
        symbols = ['000001.SZ', '600000.SH']
        for symbol in symbols:
            self.data_manager.load_data(symbol, self.test_data)
        
        loaded_symbols = self.data_manager.get_symbols()
        self.assertEqual(set(loaded_symbols), set(symbols))


if __name__ == '__main__':
    unittest.main()
