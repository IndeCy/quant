"""标准化意外盈利因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_earnings_surprise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """筛选正盈利、正意外并映射为横截面百分位得分。"""
    data = _filter_valid_earnings_surprise(frame)
    if data.empty:
        return data.assign(
            sue_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )
    lower, upper = data["sue"].quantile([0.01, 0.99])
    data["sue_winsorized"] = data["sue"].clip(lower, upper)
    data["factor_score"] = data["sue_winsorized"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return _sort_scores(data)


def score_earnings_surprise_rank_frame(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """直接按SUE秩打分，避免缩尾后TopN头部大面积同分。"""
    data = _filter_valid_earnings_surprise(frame)
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["sue"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return _sort_scores(data)


def _filter_valid_earnings_surprise(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """复用V1与V2完全相同的财务和时效过滤。"""
    required = [
        "symbol",
        "signal_date",
        "basic_eps",
        "eps_change",
        "historical_change_std",
        "history_observations",
        "sue",
        "event_age_days",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"earnings surprise frame missing columns: {missing}")
    data = frame.copy()
    numeric = [
        "basic_eps",
        "eps_change",
        "historical_change_std",
        "history_observations",
        "sue",
        "event_age_days",
    ]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(data[numeric]).all(axis=1)
    valid = (
        finite
        & data["basic_eps"].gt(0)
        & data["eps_change"].gt(0)
        & data["historical_change_std"].gt(0)
        & data["history_observations"].eq(8)
        & data["event_age_days"].between(0, 90, inclusive="both")
        & data["sue"].gt(0)
    )
    return data[valid].copy()


def _sort_scores(data: pd.DataFrame) -> pd.DataFrame:
    """按得分和代码稳定排序。"""
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
