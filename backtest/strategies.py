"""
示例策略 (Example Strategies)
包含一些常见的交易策略示例
"""

from typing import Dict
from datetime import datetime
import pandas as pd
import numpy as np

from backtest.strategy import BaseStrategy


class BuyAndHoldStrategy(BaseStrategy):
    """买入持有策略"""
    
    def __init__(self, symbol: str):
        super().__init__(name="BuyAndHold")
        self.symbol = symbol
        self.bought = False
        
    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int]:
        """在第一个交易日买入并持有"""
        if not self.bought and self.symbol in data:
            self.bought = True
            # 返回一个大的买入信号，引擎会根据可用资金调整
            return {self.symbol: 1000000}
        return {}


class MovingAverageCrossStrategy(BaseStrategy):
    """双均线策略"""
    
    def __init__(self, symbol: str, short_window: int = 5, long_window: int = 20):
        super().__init__(name="MA_Cross")
        self.symbol = symbol
        self.short_window = short_window
        self.long_window = long_window
        
    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int]:
        """
        双均线交叉策略:
        - 短期均线上穿长期均线: 买入
        - 短期均线下穿长期均线: 卖出
        """
        if self.symbol not in data:
            return {}
        
        df = data[self.symbol]
        
        # 需要足够的历史数据
        if len(df) < self.long_window:
            return {}
        
        # 计算移动平均线
        df_copy = df.copy()
        df_copy['short_ma'] = df_copy['close'].rolling(window=self.short_window).mean()
        df_copy['long_ma'] = df_copy['close'].rolling(window=self.long_window).mean()
        
        # 获取最近两天的数据
        recent = df_copy.iloc[-2:]
        
        if len(recent) < 2:
            return {}
        
        prev_short = recent.iloc[0]['short_ma']
        prev_long = recent.iloc[0]['long_ma']
        curr_short = recent.iloc[1]['short_ma']
        curr_long = recent.iloc[1]['long_ma']
        
        # 检查是否有NaN
        if pd.isna([prev_short, prev_long, curr_short, curr_long]).any():
            return {}
        
        # 金叉: 买入
        if prev_short <= prev_long and curr_short > curr_long:
            return {self.symbol: 1000000}
        
        # 死叉: 卖出
        if prev_short >= prev_long and curr_short < curr_long:
            return {self.symbol: -1000000}
        
        return {}


class MomentumStrategy(BaseStrategy):
    """动量策略"""
    
    def __init__(self, symbol: str, lookback_period: int = 20, 
                 buy_threshold: float = 0.05, sell_threshold: float = -0.03):
        super().__init__(name="Momentum")
        self.symbol = symbol
        self.lookback_period = lookback_period
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        
    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int]:
        """
        动量策略:
        - 如果过去N天收益率超过阈值: 买入
        - 如果过去N天收益率低于阈值: 卖出
        """
        if self.symbol not in data:
            return {}
        
        df = data[self.symbol]
        
        if len(df) < self.lookback_period + 1:
            return {}
        
        # 计算收益率
        current_price = df.iloc[-1]['close']
        past_price = df.iloc[-(self.lookback_period + 1)]['close']
        momentum = (current_price - past_price) / past_price
        
        # 生成信号
        if momentum > self.buy_threshold:
            return {self.symbol: 1000000}
        elif momentum < self.sell_threshold:
            return {self.symbol: -1000000}
        
        return {}


class MeanReversionStrategy(BaseStrategy):
    """均值回归策略"""
    
    def __init__(self, symbol: str, window: int = 20, num_std: float = 2.0):
        super().__init__(name="MeanReversion")
        self.symbol = symbol
        self.window = window
        self.num_std = num_std
        
    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int]:
        """
        均值回归策略 (布林带):
        - 价格跌破下轨: 买入
        - 价格突破上轨: 卖出
        """
        if self.symbol not in data:
            return {}
        
        df = data[self.symbol]
        
        if len(df) < self.window:
            return {}
        
        # 计算布林带
        df_copy = df.copy()
        df_copy['ma'] = df_copy['close'].rolling(window=self.window).mean()
        df_copy['std'] = df_copy['close'].rolling(window=self.window).std()
        df_copy['upper'] = df_copy['ma'] + self.num_std * df_copy['std']
        df_copy['lower'] = df_copy['ma'] - self.num_std * df_copy['std']
        
        current = df_copy.iloc[-1]
        
        if pd.isna([current['ma'], current['upper'], current['lower']]).any():
            return {}
        
        current_price = current['close']
        
        # 价格低于下轨: 买入
        if current_price < current['lower']:
            return {self.symbol: 1000000}
        
        # 价格高于上轨: 卖出
        if current_price > current['upper']:
            return {self.symbol: -1000000}
        
        return {}
