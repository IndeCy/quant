"""
纯价格因子轮动策略。

Milestone 1.1 只使用 OHLCV 和复权因子，不使用财务、分红或行业数据。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, Literal

import pandas as pd

from backtest.strategy import BaseStrategy
from backtest.portfolio_construction import CoreSatelliteTurnoverConstructor


PriceFactorMode = Literal["momentum", "low_volatility", "trend_following"]


class PriceFactorRotationStrategy(BaseStrategy):
    """月频纯价格因子等权轮动策略。"""

    def __init__(
        self,
        symbols: Iterable[str],
        mode: PriceFactorMode,
        top_n: int = 20,
        momentum_lookback: int = 126,
        skip_recent: int = 21,
        volatility_lookback: int = 126,
        trend_short_window: int = 20,
        trend_long_window: int = 60,
        use_stabilized_construction: bool = False,
    ):
        super().__init__(name=f"PriceFactor_{mode}")
        if top_n < 1:
            raise ValueError("top_n 必须大于 0")
        if momentum_lookback <= skip_recent:
            raise ValueError("momentum_lookback 必须大于 skip_recent")
        self.symbols = list(symbols)
        self.mode = mode
        self.top_n = top_n
        self.momentum_lookback = momentum_lookback
        self.skip_recent = skip_recent
        self.volatility_lookback = volatility_lookback
        self.trend_short_window = trend_short_window
        self.trend_long_window = trend_long_window
        self.use_stabilized_construction = use_stabilized_construction
        self._previous_weights = {symbol: 0.0 for symbol in self.symbols}
        self._constructor = CoreSatelliteTurnoverConstructor(self.symbols, top_n=top_n)
        self.current_holdings: set[str] = set()
        self._last_rebalance_month: tuple[int, int] | None = None
        self.parameters = {
            "mode": mode,
            "top_n": top_n,
            "momentum_lookback": momentum_lookback,
            "skip_recent": skip_recent,
            "volatility_lookback": volatility_lookback,
            "trend_short_window": trend_short_window,
            "trend_long_window": trend_long_window,
            "use_stabilized_construction": use_stabilized_construction,
            "rebalance": "monthly",
            "strategy_type": "纯价格因子",
        }

    def _should_rebalance(self, date: datetime) -> bool:
        """每个自然月第一个可见交易日调仓。"""
        month_key = (pd.Timestamp(date).year, pd.Timestamp(date).month)
        if month_key == self._last_rebalance_month:
            return False
        self._last_rebalance_month = month_key
        return True

    def _momentum_score(self, frame: pd.DataFrame) -> float | None:
        """过去 6 个月收益率，剔除最近 1 个月。"""
        required = self.momentum_lookback + 1
        if len(frame) < required:
            return None
        signal_price = pd.to_numeric(frame["close"].iloc[-(self.skip_recent + 1)], errors="coerce")
        base_price = pd.to_numeric(frame["close"].iloc[-required], errors="coerce")
        if pd.isna(signal_price) or pd.isna(base_price) or float(base_price) <= 0:
            return None
        return float(signal_price / base_price - 1)

    def _low_volatility_score(self, frame: pd.DataFrame) -> float | None:
        """过去 3~6 个月日收益率波动率，分数越小越好。"""
        if len(frame) < self.volatility_lookback + 1:
            return None
        returns = pd.to_numeric(frame["close"], errors="coerce").pct_change().iloc[-self.volatility_lookback:]
        volatility = returns.std()
        if pd.isna(volatility):
            return None
        return float(volatility)

    def _passes_trend_filter(self, frame: pd.DataFrame) -> bool:
        """MA20 > MA60 且价格位于 MA60 上方。"""
        if len(frame) < self.trend_long_window:
            return False
        close = pd.to_numeric(frame["close"], errors="coerce")
        ma_short = close.rolling(self.trend_short_window).mean().iloc[-1]
        ma_long = close.rolling(self.trend_long_window).mean().iloc[-1]
        current_close = close.iloc[-1]
        if pd.isna(ma_short) or pd.isna(ma_long) or pd.isna(current_close):
            return False
        return bool(ma_short > ma_long and current_close > ma_long)

    def _rank_symbols(self, data: Dict[str, pd.DataFrame]) -> list[str]:
        scores: dict[str, float] = {}
        for symbol in self.symbols:
            frame = data.get(symbol)
            if frame is None or frame.empty:
                continue
            if self.mode == "momentum":
                score = self._momentum_score(frame)
                if score is not None:
                    scores[symbol] = score
            elif self.mode == "low_volatility":
                score = self._low_volatility_score(frame)
                if score is not None:
                    scores[symbol] = score
            elif self.mode == "trend_following":
                if not self._passes_trend_filter(frame):
                    continue
                score = self._momentum_score(frame)
                if score is not None:
                    scores[symbol] = score
            else:
                raise ValueError(f"未知价格因子模式: {self.mode}")

        reverse = self.mode != "low_volatility"
        return sorted(scores, key=lambda symbol: scores[symbol], reverse=reverse)

    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, float]:
        """月频调仓，返回目标权重信号。"""
        if not self._should_rebalance(date):
            return {}

        ranked = self._rank_symbols(data)
        if self.use_stabilized_construction:
            result = self._constructor.build(ranked, self._previous_weights)
            self._previous_weights = result.target_weights.copy()
            self.current_holdings = set(result.target_holdings)
            return result.target_weights

        signals = {symbol: 0.0 for symbol in self.symbols}
        target_holdings = set(ranked[: self.top_n])
        target_weight = 1.0 / len(target_holdings) if target_holdings else 0.0
        for symbol in target_holdings:
            signals[symbol] = target_weight
        self._previous_weights = signals.copy()
        self.current_holdings = set(target_holdings)
        return signals
