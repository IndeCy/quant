"""Quality 因子快照到策略分数的标准适配。"""

from __future__ import annotations

import pandas as pd

from factors.quality import score_quality_frame
from portfolio.topn import build_topn_selections


def build_quality_scores(candidates: pd.DataFrame) -> pd.DataFrame:
    """逐个信号日计算 Quality V1 分数，不在这里决定权重。"""
    if "signal_date" not in candidates.columns:
        raise ValueError("quality candidates missing columns: ['signal_date']")
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_frame(group)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    return pd.concat(frames, ignore_index=True) if frames else candidates.iloc[0:0].copy()


def build_quality_topn(
    candidates: pd.DataFrame,
    *,
    top_n: int = 20,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """生成 Quality 排名并交由通用组合层选出 TopN。"""
    scores = build_quality_scores(candidates)
    return build_topn_selections(scores, "quality_score", top_n)
