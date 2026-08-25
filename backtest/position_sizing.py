"""
仓位管理模块

第一版以凯利公式为基础，输出保守的仓位建议。
模块只负责计算建议仓位，不直接执行交易，避免把风险控制和下单执行耦合。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd


@dataclass(frozen=True)
class KellyEstimate:
    """凯利公式所需的历史统计估计。"""

    win_rate: float
    win_loss_ratio: float
    raw_fraction: float
    sample_size: int


@dataclass(frozen=True)
class PositionSizingSuggestion:
    """仓位建议结果。"""

    total_exposure: float
    reason: str
    raw_fraction: float
    fractional_kelly: float
    max_total_exposure: float


def calculate_kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
    """
    计算标准凯利仓位。

    公式：f = p - (1 - p) / b
    p 为胜率，b 为平均盈利/平均亏损的赔率。
    当优势为负时返回 0，表示不建议主动下注。
    """
    if not 0 <= win_rate <= 1:
        raise ValueError("win_rate 必须在 0 到 1 之间")
    if win_loss_ratio <= 0:
        return 0.0
    fraction = win_rate - (1 - win_rate) / win_loss_ratio
    return max(0.0, float(fraction))


def estimate_kelly_from_returns(returns: pd.Series) -> KellyEstimate:
    """从历史收益序列估计胜率、赔率和原始凯利仓位。"""
    clean_returns = returns.dropna()
    sample_size = int(len(clean_returns))
    if sample_size == 0:
        return KellyEstimate(0.0, 0.0, 0.0, 0)

    wins = clean_returns[clean_returns > 0]
    losses = clean_returns[clean_returns < 0]
    win_rate = float(len(wins) / sample_size)
    if losses.empty or wins.empty:
        win_loss_ratio = 0.0
    else:
        # 赔率使用平均盈利除以平均亏损绝对值，避免亏损为负导致方向错误。
        win_loss_ratio = float(wins.mean() / abs(losses.mean()))
    raw_fraction = calculate_kelly_fraction(win_rate, win_loss_ratio)
    return KellyEstimate(win_rate, win_loss_ratio, raw_fraction, sample_size)


class KellyPositionSizer:
    """基于凯利公式的保守仓位建议器。"""

    def __init__(
        self,
        fractional_kelly: float = 0.5,
        max_total_exposure: float = 1.0,
        min_sample_size: int = 20,
    ):
        if not 0 <= fractional_kelly <= 1:
            raise ValueError("fractional_kelly 必须在 0 到 1 之间")
        if not 0 <= max_total_exposure <= 1:
            raise ValueError("max_total_exposure 必须在 0 到 1 之间")
        if min_sample_size < 1:
            raise ValueError("min_sample_size 必须大于 0")
        self.fractional_kelly = fractional_kelly
        self.max_total_exposure = max_total_exposure
        self.min_sample_size = min_sample_size

    def suggest_total_exposure(self, estimate: KellyEstimate) -> PositionSizingSuggestion:
        """根据凯利估计生成总仓位建议。"""
        if estimate.sample_size < self.min_sample_size:
            return PositionSizingSuggestion(
                total_exposure=0.0,
                reason="INSUFFICIENT_SAMPLE",
                raw_fraction=estimate.raw_fraction,
                fractional_kelly=self.fractional_kelly,
                max_total_exposure=self.max_total_exposure,
            )

        exposure = min(
            estimate.raw_fraction * self.fractional_kelly,
            self.max_total_exposure,
        )
        return PositionSizingSuggestion(
            total_exposure=float(max(0.0, exposure)),
            reason="KELLY" if exposure > 0 else "NO_EDGE",
            raw_fraction=estimate.raw_fraction,
            fractional_kelly=self.fractional_kelly,
            max_total_exposure=self.max_total_exposure,
        )

    def allocate_equal_weights(self, symbols: List[str], total_exposure: float) -> Dict[str, float]:
        """把总仓位等权分配给目标股票。"""
        unique_symbols = list(dict.fromkeys(symbols))
        if not unique_symbols or total_exposure <= 0:
            return {symbol: 0.0 for symbol in unique_symbols}
        weight = float(total_exposure / len(unique_symbols))
        return {symbol: weight for symbol in unique_symbols}
