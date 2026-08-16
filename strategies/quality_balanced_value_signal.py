"""Quality主体叠加少量E/P与B/P的标准信号生成。"""

from __future__ import annotations

import math

import pandas as pd

from factors.quality_market_extension import score_quality_market_extension
from portfolio.topn import build_topn_selections


EXPECTED_WEIGHTS = {
    "roe": 0.8 / 3,
    "roa": 0.8 / 3,
    "ocf_to_or": 0.8 / 3,
    "earnings_yield": 0.10,
    "book_yield": 0.10,
}


def build_quality_balanced_value_topn(
    candidates: pd.DataFrame,
    factor_weights: dict[str, float],
    *,
    top_n: int,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """策略层只生成综合分数，TopN仍交给通用组合层。"""
    _validate_weights(factor_weights)
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_market_extension(
            group,
            {"earnings_yield": 0.10, "book_yield": 0.10},
        )
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    scores = (
        pd.concat(frames, ignore_index=True)
        if frames
        else candidates.iloc[0:0].copy()
    )
    return build_topn_selections(scores, "factor_score", top_n)


def _validate_weights(factor_weights: dict[str, float]) -> None:
    """运行配置必须与研究通过的冻结权重完全一致。"""
    if set(factor_weights) != set(EXPECTED_WEIGHTS):
        raise ValueError("quality balanced value factor set does not match frozen contract")
    invalid = [
        factor
        for factor, expected in EXPECTED_WEIGHTS.items()
        if not math.isclose(float(factor_weights[factor]), expected, abs_tol=1e-9)
    ]
    if invalid:
        raise ValueError(f"quality balanced value weights changed: {invalid}")
