"""Quality Balanced Value 的五年盈利底线过滤。"""

from __future__ import annotations

import pandas as pd

from factors.quality_market_extension import score_quality_market_extension
from portfolio.topn import build_topn_selections
from strategies.quality_balanced_value_signal import EXPECTED_WEIGHTS


def apply_positive_profitability_floor(frame: pd.DataFrame) -> pd.DataFrame:
    """只保留最近五个连续年报中最低 ROA 仍为正的公司。"""
    required = {
        "signal_date",
        "symbol",
        "roa_floor_5y",
        "observations",
        "latest_publish_date",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"profitability floor frame missing columns: {missing}")
    data = frame.copy()
    floor = pd.to_numeric(data["roa_floor_5y"], errors="coerce")
    observations = pd.to_numeric(data["observations"], errors="coerce")
    visible = (
        data["latest_publish_date"].astype(str)
        <= data["signal_date"].astype(str)
    )
    return data[
        floor.gt(0)
        & observations.eq(5)
        & visible
    ].copy()


def build_quality_profitability_floor_topn(
    candidates: pd.DataFrame,
    factor_weights: dict[str, float],
    *,
    top_n: int,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """先按完整 Quality 截面评分，再把盈利底线仅作为资格过滤。"""
    if factor_weights != EXPECTED_WEIGHTS:
        raise ValueError("quality profitability floor weights changed")
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_market_extension(
            group,
            {"earnings_yield": 0.10, "book_yield": 0.10},
        )
        scored["signal_date"] = str(signal_date)
        frames.append(apply_positive_profitability_floor(scored))
    scores = (
        pd.concat(frames, ignore_index=True)
        if frames
        else candidates.iloc[0:0].copy()
    )
    return build_topn_selections(scores, "factor_score", top_n)
