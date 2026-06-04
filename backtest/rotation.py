"""
行业轮动策略模块

提供基于行业指数动量的低频轮动策略。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set

import pandas as pd

from backtest.strategy import BaseStrategy


class IndustryMomentumRotationStrategy(BaseStrategy):
    """行业动量轮动策略"""

    def __init__(
        self,
        symbols: List[str],
        lookback_period: int = 20,
        top_n: int = 3,
        rebalance_frequency: int = 5,
        market_filter_symbol: Optional[str] = None,
        market_ma_window: int = 20,
        industry_ma_window: Optional[int] = None,
        use_target_weight: bool = False,
        momentum_windows: Optional[List[int]] = None,
        holding_buffer_rank: Optional[int] = None,
    ):
        super().__init__(name="Industry_Momentum_Rotation")
        if top_n < 1:
            raise ValueError("top_n 必须大于 0")
        if lookback_period < 1:
            raise ValueError("lookback_period 必须大于 0")
        if rebalance_frequency < 1:
            raise ValueError("rebalance_frequency 必须大于 0")

        self.symbols = symbols
        self.lookback_period = lookback_period
        self.top_n = top_n
        self.rebalance_frequency = rebalance_frequency
        self.market_filter_symbol = market_filter_symbol
        self.market_ma_window = market_ma_window
        self.industry_ma_window = industry_ma_window
        self.use_target_weight = use_target_weight
        self.momentum_windows = momentum_windows or [lookback_period]
        self.holding_buffer_rank = holding_buffer_rank
        self.current_holdings: Set[str] = set()
        self._last_rebalance_length: Optional[int] = None
        self.parameters = {
            "lookback_period": lookback_period,
            "top_n": top_n,
            "rebalance_frequency": rebalance_frequency,
            "market_filter_symbol": market_filter_symbol or "",
            "market_ma_window": market_ma_window,
            "industry_ma_window": industry_ma_window or 0,
            "use_target_weight": use_target_weight,
            "momentum_windows": self.momentum_windows,
            "holding_buffer_rank": holding_buffer_rank or 0,
            "strategy_type": "行业轮动",
        }

    def _reference_length(self, data: Dict[str, pd.DataFrame]) -> int:
        """取第一个可用行业数据长度作为调仓节奏参考。"""
        for symbol in self.symbols:
            if symbol in data:
                return len(data[symbol])
        return 0

    def _should_rebalance(self, data: Dict[str, pd.DataFrame]) -> bool:
        """判断是否到达调仓日。"""
        current_length = self._reference_length(data)
        if current_length == 0:
            return False
        if self._last_rebalance_length is None:
            return True
        return current_length - self._last_rebalance_length >= self.rebalance_frequency

    def _is_market_weak(self, data: Dict[str, pd.DataFrame]) -> bool:
        """基准指数低于均线时视为弱市，行业轮动清仓防守。"""
        if not self.market_filter_symbol:
            return False
        if self.market_filter_symbol not in data:
            return False

        market_df = data[self.market_filter_symbol]
        if len(market_df) < self.market_ma_window:
            return False

        close = market_df["close"]
        moving_average = close.rolling(window=self.market_ma_window).mean().iloc[-1]
        return bool(close.iloc[-1] < moving_average)

    def _calculate_momentum_scores(self, data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """计算行业多周期平均收益率作为动量分数。"""
        scores: Dict[str, float] = {}
        for symbol in self.symbols:
            if symbol not in data:
                continue
            df = data[symbol]
            if len(df) < max(self.momentum_windows) + 1:
                continue
            current_close = float(df["close"].iloc[-1])
            returns = []
            for window in self.momentum_windows:
                past_close = float(df["close"].iloc[-(window + 1)])
                if past_close != 0:
                    returns.append(current_close / past_close - 1)
            if returns:
                scores[symbol] = float(sum(returns) / len(returns))
        return scores

    def _select_target_holdings(self, ranked_symbols: List[str]) -> Set[str]:
        """根据排名和缓冲区生成目标持仓。"""
        if not self.holding_buffer_rank or not self.current_holdings:
            return set(ranked_symbols[: self.top_n])

        buffer_symbols = set(ranked_symbols[: self.holding_buffer_rank])
        kept = [symbol for symbol in ranked_symbols if symbol in self.current_holdings and symbol in buffer_symbols]
        targets = kept[: self.top_n]
        for symbol in ranked_symbols:
            if len(targets) >= self.top_n:
                break
            if symbol not in targets:
                targets.append(symbol)
        return set(targets)

    def _passes_industry_trend_filter(self, symbol: str, data: Dict[str, pd.DataFrame]) -> bool:
        """行业价格站上自身均线时才允许进入候选池。"""
        if not self.industry_ma_window:
            return True
        if symbol not in data:
            return False
        df = data[symbol]
        if len(df) < self.industry_ma_window:
            return False
        close = df["close"]
        moving_average = close.rolling(window=self.industry_ma_window).mean().iloc[-1]
        return bool(close.iloc[-1] >= moving_average)

    def _build_rebalance_signals(self, target_holdings: Set[str]) -> Dict[str, int | float]:
        """根据目标持仓生成先卖后买的调仓信号。"""
        if self.use_target_weight:
            target_weight = 1.0 / len(target_holdings) if target_holdings else 0.0
            signals = {symbol: 0.0 for symbol in sorted(self.symbols)}
            for symbol in sorted(target_holdings):
                signals[symbol] = target_weight
            self.current_holdings = set(target_holdings)
            return signals

        signals: Dict[str, int] = {}
        for symbol in sorted(self.current_holdings - target_holdings):
            signals[symbol] = -1000000
        for symbol in sorted(target_holdings - self.current_holdings):
            signals[symbol] = 1000000
        self.current_holdings = set(target_holdings)
        return signals

    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, int | float]:
        """
        生成行业轮动信号:
        - 每 rebalance_frequency 个交易日调仓一次
        - 选择过去 lookback_period 日收益最高的 top_n 个行业
        - 若开启市场过滤且基准跌破均线，则清仓防守
        """
        if not self._should_rebalance(data):
            return {}

        self._last_rebalance_length = self._reference_length(data)
        if self._is_market_weak(data):
            return self._build_rebalance_signals(set())

        scores = self._calculate_momentum_scores(data)
        if not scores:
            return {}

        eligible_symbols = [
            symbol for symbol in scores
            if self._passes_industry_trend_filter(symbol, data)
        ]
        ranked_symbols = sorted(eligible_symbols, key=lambda symbol: scores[symbol], reverse=True)
        target_holdings = self._select_target_holdings(ranked_symbols)
        return self._build_rebalance_signals(target_holdings)
