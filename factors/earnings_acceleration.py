"""业绩快报利润增长加速度因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_earnings_acceleration_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """筛选正增长且继续加速的公司，并映射为百分位分数。"""
    required = [
        "symbol",
        "signal_date",
        "current_net_income",
        "prior_year_net_income",
        "profit_growth",
        "prior_profit_growth",
        "profit_acceleration",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"earnings acceleration frame missing columns: {missing}")

    data = frame.copy()
    numeric = [
        "current_net_income",
        "prior_year_net_income",
        "profit_growth",
        "prior_profit_growth",
        "profit_acceleration",
    ]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(data[numeric]).all(axis=1)
    valid &= data["current_net_income"].gt(0)
    valid &= data["prior_year_net_income"].gt(0)
    valid &= data["profit_growth"].gt(0)
    valid &= data["profit_acceleration"].gt(0)
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))

    data["factor_score"] = data["profit_acceleration"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)


def score_persistent_earnings_acceleration_frame(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """要求上一年度也为正增长，排除亏损后低基数反转。"""
    data = score_earnings_acceleration_frame(frame)
    if data.empty:
        return data
    data = data[data["prior_profit_growth"].gt(0)].copy()
    if data.empty:
        return data
    data["factor_score"] = data["profit_acceleration"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
