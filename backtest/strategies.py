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
        self.parameters = {"strategy_type": "基线"}
        
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
        self.parameters = {
            "short_window": short_window,
            "long_window": long_window,
            "strategy_type": "趋势跟随",
        }
        
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
        self.parameters = {
            "lookback_period": lookback_period,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "strategy_type": "趋势跟随",
        }
        
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
        self.parameters = {
            "window": window,
            "num_std": num_std,
            "strategy_type": "均值回归",
        }
        
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


class DonchianChannelBreakoutStrategy(BaseStrategy):
    """唐奇安通道突破策略"""

    def __init__(self, symbol: str, entry_window: int = 20, exit_window: int = 10):
        super().__init__(name="Donchian_Channel_Breakout")
        self.symbol = symbol
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.parameters = {
            "entry_window": entry_window,
            "exit_window": exit_window,
            "strategy_type": "趋势跟随",
        }

    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int]:
        """
        唐奇安通道:
        - 当前收盘价突破前 entry_window 日最高价: 买入
        - 当前收盘价跌破前 exit_window 日最低价: 卖出
        """
        if self.symbol not in data:
            return {}

        df = data[self.symbol]
        required = max(self.entry_window, self.exit_window) + 1
        if len(df) < required:
            return {}

        current_close = df.iloc[-1]["close"]
        entry_high = df["high"].iloc[-(self.entry_window + 1):-1].max()
        exit_low = df["low"].iloc[-(self.exit_window + 1):-1].min()

        if current_close > entry_high:
            return {self.symbol: 1000000}
        if current_close < exit_low:
            return {self.symbol: -1000000}
        return {}


class TurtleTradingStrategy(BaseStrategy):
    """海龟交易法策略"""

    def __init__(
        self,
        symbol: str,
        entry_window: int = 20,
        exit_window: int = 10,
        atr_window: int = 14,
        atr_multiplier: float = 2.0,
    ):
        super().__init__(name="Turtle_Trading")
        self.symbol = symbol
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.atr_window = atr_window
        self.atr_multiplier = atr_multiplier
        self.entry_price = None
        self.parameters = {
            "entry_window": entry_window,
            "exit_window": exit_window,
            "atr_window": atr_window,
            "atr_multiplier": atr_multiplier,
            "strategy_type": "趋势跟随",
        }

    def _calculate_atr(self, df: pd.DataFrame) -> float:
        """计算 ATR，用于海龟策略的波动止损。"""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return float(true_range.rolling(window=self.atr_window).mean().iloc[-1])

    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int]:
        """
        海龟交易法:
        - 突破前 entry_window 日高点买入
        - 跌破前 exit_window 日低点卖出
        - 买入后若跌破 entry_price - ATR倍数 止损卖出
        """
        if self.symbol not in data:
            return {}

        df = data[self.symbol]
        required = max(self.entry_window, self.exit_window, self.atr_window) + 1
        if len(df) < required:
            return {}

        current_close = float(df.iloc[-1]["close"])
        entry_high = float(df["high"].iloc[-(self.entry_window + 1):-1].max())
        exit_low = float(df["low"].iloc[-(self.exit_window + 1):-1].min())
        atr = self._calculate_atr(df)

        if self.entry_price is not None and not np.isnan(atr):
            stop_price = self.entry_price - self.atr_multiplier * atr
            if current_close <= stop_price:
                self.entry_price = None
                return {self.symbol: -1000000}

        if current_close > entry_high:
            self.entry_price = current_close
            return {self.symbol: 1000000}

        if current_close < exit_low:
            self.entry_price = None
            return {self.symbol: -1000000}

        return {}


class RSIStrategy(BaseStrategy):
    """RSI 超买超卖策略"""

    def __init__(self, symbol: str, window: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        super().__init__(name="RSI_Reversion")
        self.symbol = symbol
        self.window = window
        self.oversold = oversold
        self.overbought = overbought
        self.parameters = {
            "window": window,
            "oversold": oversold,
            "overbought": overbought,
            "strategy_type": "均值回归",
        }

    def _calculate_rsi(self, close: pd.Series) -> float:
        """计算 RSI 指标，连续下跌时 RSI 接近 0，连续上涨时接近 100。"""
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=self.window).mean()
        loss = (-delta.clip(upper=0)).rolling(window=self.window).mean()
        avg_gain = gain.iloc[-1]
        avg_loss = loss.iloc[-1]
        if pd.isna(avg_gain) or pd.isna(avg_loss):
            return np.nan
        if avg_loss == 0:
            return 100.0
        relative_strength = avg_gain / avg_loss
        return float(100 - (100 / (1 + relative_strength)))

    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int]:
        """
        RSI 策略:
        - RSI 低于 oversold: 买入
        - RSI 高于 overbought: 卖出
        """
        if self.symbol not in data:
            return {}

        df = data[self.symbol]
        if len(df) < self.window + 1:
            return {}

        rsi = self._calculate_rsi(df["close"])
        if np.isnan(rsi):
            return {}
        if rsi < self.oversold:
            return {self.symbol: 1000000}
        if rsi > self.overbought:
            return {self.symbol: -1000000}
        return {}


class BollingerBandStrategy(BaseStrategy):
    """布林带策略，支持回归和突破两种模式"""

    def __init__(self, symbol: str, window: int = 20, num_std: float = 2.0, mode: str = "reversion"):
        super().__init__(name=f"Bollinger_{mode}")
        if mode not in {"reversion", "breakout"}:
            raise ValueError("mode 只能是 reversion 或 breakout")
        self.symbol = symbol
        self.window = window
        self.num_std = num_std
        self.mode = mode
        self.parameters = {
            "window": window,
            "num_std": num_std,
            "mode": mode,
            "strategy_type": "均值回归" if mode == "reversion" else "趋势跟随",
        }

    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int]:
        """
        布林带策略:
        - 回归模式: 跌破下轨买入，突破上轨卖出
        - 突破模式: 突破上轨买入，跌破中轨卖出
        """
        if self.symbol not in data:
            return {}

        df = data[self.symbol]
        if len(df) < self.window:
            return {}

        close = df["close"]
        middle = close.rolling(window=self.window).mean().iloc[-1]
        std = close.rolling(window=self.window).std().iloc[-1]
        if pd.isna(middle) or pd.isna(std):
            return {}

        upper = middle + self.num_std * std
        lower = middle - self.num_std * std
        current_close = close.iloc[-1]

        if self.mode == "reversion":
            if current_close < lower:
                return {self.symbol: 1000000}
            if current_close > upper:
                return {self.symbol: -1000000}
        else:
            if current_close > upper:
                return {self.symbol: 1000000}
            if current_close < middle:
                return {self.symbol: -1000000}

        return {}
