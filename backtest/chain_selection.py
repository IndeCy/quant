"""
产业链选股策略模块

提供三类可复现选股方式：
- single_chain：先指定产业链，再在链内选股
- multi_chain：先比较产业链强度，再在强链内选股
- whole_pool：忽略产业链分组，从全股票池直接选股
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set

import pandas as pd

from backtest.strategy import BaseStrategy


@dataclass(frozen=True)
class ChainStock:
    """产业链内的个股定义。"""

    symbol: str
    name: str
    chain: str
    segment: str


@dataclass(frozen=True)
class ChainDefinition:
    """产业链定义，包含代理标的和链内个股。"""

    name: str
    proxy_symbol: str
    stocks: List[ChainStock]


class ChainStockSelectionStrategy(BaseStrategy):
    """产业链选股策略，输出等权目标仓位。"""

    def __init__(
        self,
        chains: List[ChainDefinition],
        mode: str,
        target_chain: Optional[str] = None,
        top_n: int = 5,
        rebalance_frequency: int = 5,
        momentum_windows: Optional[List[int]] = None,
        chain_momentum_window: int = 20,
        chain_gate_symbol: Optional[str] = None,
        drawdown_penalty: float = 0.2,
    ):
        super().__init__(name=f"Chain_Stock_Selection_{mode}")
        if mode not in {"single_chain", "multi_chain", "whole_pool"}:
            raise ValueError("mode 仅支持 single_chain/multi_chain/whole_pool")
        if top_n < 1:
            raise ValueError("top_n 必须大于 0")
        if rebalance_frequency < 1:
            raise ValueError("rebalance_frequency 必须大于 0")

        self.chains = chains
        self.mode = mode
        self.target_chain = target_chain
        self.top_n = top_n
        self.rebalance_frequency = rebalance_frequency
        self.momentum_windows = momentum_windows or [20, 60]
        self.chain_momentum_window = chain_momentum_window
        self.chain_gate_symbol = chain_gate_symbol
        self.drawdown_penalty = drawdown_penalty
        self.current_holdings: Set[str] = set()
        self._last_rebalance_length: Optional[int] = None
        self.parameters = {
            "mode": mode,
            "target_chain": target_chain or "",
            "top_n": top_n,
            "rebalance_frequency": rebalance_frequency,
            "momentum_windows": self.momentum_windows,
            "chain_momentum_window": chain_momentum_window,
            "chain_gate_symbol": chain_gate_symbol or "",
            "drawdown_penalty": drawdown_penalty,
            "strategy_type": "产业链选股",
        }

    def _all_stocks(self) -> List[ChainStock]:
        """展开全部产业链股票池。"""
        stocks: List[ChainStock] = []
        for chain in self.chains:
            stocks.extend(chain.stocks)
        return stocks

    def _reference_length(self, data: Dict[str, pd.DataFrame]) -> int:
        """使用第一个可用股票数据作为调仓节奏参考。"""
        for stock in self._all_stocks():
            if stock.symbol in data:
                return len(data[stock.symbol])
        return 0

    def _should_rebalance(self, data: Dict[str, pd.DataFrame]) -> bool:
        """判断是否到达调仓日。"""
        current_length = self._reference_length(data)
        if current_length == 0:
            return False
        if self._last_rebalance_length is None:
            return True
        return current_length - self._last_rebalance_length >= self.rebalance_frequency

    def _momentum(self, df: pd.DataFrame, window: int) -> Optional[float]:
        """计算指定窗口收益率。"""
        if len(df) < window + 1:
            return None
        past_close = float(df["close"].iloc[-(window + 1)])
        if past_close == 0:
            return None
        return float(df["close"].iloc[-1]) / past_close - 1

    def _score_stock(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[float]:
        """用多周期动量减去回撤惩罚，形成链内选股分数。"""
        if symbol not in data:
            return None
        df = data[symbol]
        returns = [
            value for window in self.momentum_windows
            if (value := self._momentum(df, window)) is not None
        ]
        if not returns:
            return None

        # 回撤惩罚用于规避短期暴拉后快速回落的个股。
        lookback = min(max(self.momentum_windows) + 1, len(df))
        closes = df["close"].iloc[-lookback:]
        drawdown = float((closes / closes.cummax() - 1).min())
        return float(sum(returns) / len(returns) + self.drawdown_penalty * drawdown)

    def _chain_score(self, chain: ChainDefinition, data: Dict[str, pd.DataFrame]) -> Optional[float]:
        """优先用产业链代理标的强度打分，缺失时用链内个股平均分兜底。"""
        if chain.proxy_symbol in data:
            return self._momentum(data[chain.proxy_symbol], self.chain_momentum_window)

        stock_scores = [
            score for stock in chain.stocks
            if (score := self._score_stock(stock.symbol, data)) is not None
        ]
        if not stock_scores:
            return None
        return float(sum(stock_scores) / len(stock_scores))

    def _find_chain(self, name: str) -> Optional[ChainDefinition]:
        """按产业链名称查找定义。"""
        for chain in self.chains:
            if chain.name == name:
                return chain
        return None

    def _single_chain_candidates(self, data: Dict[str, pd.DataFrame]) -> List[ChainStock]:
        """A方案候选池：指定产业链内个股。"""
        if not self.target_chain:
            return []
        chain = self._find_chain(self.target_chain)
        if chain is None:
            return []
        return chain.stocks

    def _multi_chain_candidates(self, data: Dict[str, pd.DataFrame]) -> List[ChainStock]:
        """B方案候选池：强度最高的产业链内个股。"""
        scored_chains = [
            (chain, score) for chain in self.chains
            if (score := self._chain_score(chain, data)) is not None
        ]
        if not scored_chains:
            return []
        best_chain = max(scored_chains, key=lambda item: item[1])[0]
        return best_chain.stocks

    def _is_chain_blocked(self, chain: ChainDefinition, data: Dict[str, pd.DataFrame]) -> bool:
        """当目标链代理弱于基线时，不启用该产业链。"""
        if not self.chain_gate_symbol or self.chain_gate_symbol not in data:
            return False
        if chain.proxy_symbol not in data:
            return False
        chain_score = self._momentum(data[chain.proxy_symbol], self.chain_momentum_window)
        gate_score = self._momentum(data[self.chain_gate_symbol], self.chain_momentum_window)
        if chain_score is None or gate_score is None:
            return False
        return chain_score < gate_score

    def _candidate_stocks(self, data: Dict[str, pd.DataFrame]) -> List[ChainStock]:
        """根据模式返回本次可参与排序的股票池。"""
        if self.mode == "single_chain":
            return self._single_chain_candidates(data)
        if self.mode == "multi_chain":
            return self._multi_chain_candidates(data)
        return self._all_stocks()

    def _build_target_weight_signals(self, candidates: List[ChainStock], targets: Set[str]) -> Dict[str, float]:
        """把目标股票集合转成等权调仓信号。"""
        target_weight = 1.0 / len(targets) if targets else 0.0
        candidate_symbols = sorted({stock.symbol for stock in candidates} | self.current_holdings)
        signals = {symbol: 0.0 for symbol in candidate_symbols}
        for symbol in targets:
            signals[symbol] = target_weight
        self.current_holdings = set(targets)
        return signals

    def generate_signals(self, data: Dict[str, pd.DataFrame], date: datetime) -> Dict[str, float]:
        """生成等权目标仓位信号。"""
        if not self._should_rebalance(data):
            return {}
        self._last_rebalance_length = self._reference_length(data)

        candidates = self._candidate_stocks(data)
        if self.mode == "single_chain" and self.target_chain:
            chain = self._find_chain(self.target_chain)
            if chain is not None and self._is_chain_blocked(chain, data):
                return self._build_target_weight_signals(candidates, set())

        scores = [
            (stock.symbol, score) for stock in candidates
            if (score := self._score_stock(stock.symbol, data)) is not None
        ]
        ranked = sorted(scores, key=lambda item: item[1], reverse=True)
        targets = {symbol for symbol, _ in ranked[: self.top_n]}
        return self._build_target_weight_signals(candidates, targets)
