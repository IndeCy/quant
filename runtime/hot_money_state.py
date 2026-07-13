"""游资情绪市场状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class MarketState(str, Enum):
    """A 股短线情绪状态。"""

    ICE_COLD = "ICE_COLD"
    REBOUND = "REBOUND"
    EXPANSION = "EXPANSION"
    BUBBLE = "BUBBLE"
    DISTRIBUTION = "DISTRIBUTION"


STATE_ORDER = [
    MarketState.ICE_COLD,
    MarketState.REBOUND,
    MarketState.EXPANSION,
    MarketState.BUBBLE,
    MarketState.DISTRIBUTION,
]
STATE_COLUMNS = ["trade_date", "raw_state", "smoothed_state", "emotion_score", "risk_score", "transition_reason"]


@dataclass(frozen=True)
class MarketStateEngine:
    """短线情绪状态机，只识别状态，不预测明天。"""

    def classify_series(self, emotion: pd.DataFrame) -> pd.DataFrame:
        """对时间序列情绪数据做单日初判和平滑状态输出。"""
        if emotion.empty:
            return pd.DataFrame(columns=STATE_COLUMNS)
        rows = emotion.sort_values("trade_date").reset_index(drop=True)
        outputs: list[dict[str, object]] = []
        previous = MarketState.ICE_COLD
        for _, row in rows.iterrows():
            emotion_score = _emotion_score(row)
            risk_score = _risk_score(row)
            raw_state = _raw_state(row, emotion_score, risk_score)
            smoothed, reason = _smooth_transition(previous, raw_state, risk_score, int(row.get("limit_down_count", 0)))
            outputs.append(
                {
                    "trade_date": str(row["trade_date"]),
                    "raw_state": raw_state.value,
                    "smoothed_state": smoothed.value,
                    "emotion_score": emotion_score,
                    "risk_score": risk_score,
                    "transition_reason": reason,
                }
            )
            previous = smoothed
        return pd.DataFrame(outputs, columns=STATE_COLUMNS)


def _emotion_score(row: pd.Series) -> float:
    """情绪分：涨停和成交放大加分，跌停和炸板扣分。"""
    up = min(float(row.get("limit_up_count", 0)) / 100.0, 1.0)
    down_penalty = min(float(row.get("limit_down_count", 0)) / 80.0, 1.0)
    board_penalty = min(float(row.get("open_board_rate", 0)), 1.5) / 1.5
    amount_change = max(min(float(row.get("market_amount_chg", 0)), 0.3), -0.3)
    amount_bonus = amount_change / 0.6 + 0.5
    score = 100 * (0.50 * up + 0.20 * amount_bonus + 0.15 * (1 - down_penalty) + 0.15 * (1 - board_penalty))
    return round(max(0.0, min(score, 100.0)), 2)


def _risk_score(row: pd.Series) -> float:
    """风险分：跌停、炸板率、炸板数量共同刻画退潮风险。"""
    down = min(float(row.get("limit_down_count", 0)) / 80.0, 1.0)
    open_rate = min(float(row.get("open_board_rate", 0)), 1.5) / 1.5
    zha = min(float(row.get("zha_ban_count", 0)) / 80.0, 1.0)
    score = 100 * (0.45 * down + 0.35 * open_rate + 0.20 * zha)
    return round(max(0.0, min(score, 100.0)), 2)


def _raw_state(row: pd.Series, emotion_score: float, risk_score: float) -> MarketState:
    """用固定阈值做单日初判，后续再由平滑器限制跳变。"""
    up = int(row.get("limit_up_count", 0))
    down = int(row.get("limit_down_count", 0))
    if risk_score >= 65 or down >= 35:
        return MarketState.DISTRIBUTION
    if up <= 10 or emotion_score < 30:
        return MarketState.ICE_COLD
    if emotion_score < 50:
        return MarketState.REBOUND
    if emotion_score < 72:
        return MarketState.EXPANSION
    return MarketState.BUBBLE


def _smooth_transition(
    previous: MarketState,
    raw_state: MarketState,
    risk_score: float,
    limit_down_count: int,
) -> tuple[MarketState, str]:
    """限制普通状态单日跨级跳变，极端风险可直入退潮。"""
    if raw_state == MarketState.DISTRIBUTION and (risk_score >= 65 or limit_down_count >= 35):
        return MarketState.DISTRIBUTION, "极端风险触发，直接进入退潮"
    if raw_state == previous:
        return raw_state, "状态延续"
    if previous == MarketState.DISTRIBUTION and raw_state == MarketState.BUBBLE:
        return MarketState.REBOUND, "退潮后先进入修复，不允许单日主升"
    previous_index = STATE_ORDER.index(previous)
    raw_index = STATE_ORDER.index(raw_state)
    if abs(raw_index - previous_index) <= 1:
        return raw_state, f"状态平滑切换: {previous.value}->{raw_state.value}"
    step = 1 if raw_index > previous_index else -1
    limited = STATE_ORDER[previous_index + step]
    return limited, f"限制单日跳变: {previous.value}->{raw_state.value}，平滑为{limited.value}"
