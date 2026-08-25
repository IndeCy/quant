"""Quality Value LowVol 因子分数到 TopN 信号的标准适配。"""

from __future__ import annotations

import pandas as pd

from factors.quality_value_lowvol import score_quality_value_lowvol_frame
from portfolio.topn import build_topn_selections


def build_quality_value_lowvol_scores(
    candidates: pd.DataFrame,
    factor_weights: dict[str, float],
) -> pd.DataFrame:
    """逐月计算五因子分数，策略层不决定股票权重。"""
    if "signal_date" not in candidates.columns:
        raise ValueError("quality value lowvol candidates missing signal_date")
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_value_lowvol_frame(group, factor_weights)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    return pd.concat(frames, ignore_index=True) if frames else candidates.iloc[0:0].copy()


def build_quality_value_lowvol_topn(
    candidates: pd.DataFrame,
    factor_weights: dict[str, float],
    *,
    top_n: int,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """将策略分数交给通用组合层生成稳定 TopN 名单。"""
    scores = build_quality_value_lowvol_scores(candidates, factor_weights)
    return build_topn_selections(scores, "factor_score", top_n)
