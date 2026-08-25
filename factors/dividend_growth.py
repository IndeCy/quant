"""连续现金分红增长因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.quality import winsorize_series, zscore_series


def score_dividend_growth_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """按最近两次年度分红增长率中的较小值打分。

    三年必须连续有正现金分红，且两次同比都不能下降。使用较小增长率可以
    奖励持续性，并降低单年一次性高分红对排名的影响。
    """
    required = [
        "symbol",
        "signal_date",
        "cash_payout_y0",
        "cash_payout_y1",
        "cash_payout_y2",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"dividend growth frame missing columns: {missing}")

    data = frame.copy()
    payout_columns = ["cash_payout_y0", "cash_payout_y1", "cash_payout_y2"]
    data[payout_columns] = data[payout_columns].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(data[payout_columns]).all(axis=1)
    valid &= data[payout_columns].gt(0).all(axis=1)
    data = data[valid].copy()
    if data.empty:
        return data.assign(
            dividend_growth_latest=pd.Series(dtype=float),
            dividend_growth_prior=pd.Series(dtype=float),
            dividend_growth_floor=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )

    data["dividend_growth_latest"] = (
        data["cash_payout_y0"] / data["cash_payout_y1"] - 1.0
    )
    data["dividend_growth_prior"] = (
        data["cash_payout_y1"] / data["cash_payout_y2"] - 1.0
    )
    data = data[
        data["dividend_growth_latest"].ge(0)
        & data["dividend_growth_prior"].ge(0)
    ].copy()
    if data.empty:
        return data.assign(
            dividend_growth_floor=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )

    data["dividend_growth_floor"] = data[
        ["dividend_growth_latest", "dividend_growth_prior"]
    ].min(axis=1)
    clipped = winsorize_series(
        data["dividend_growth_floor"],
        lower=0.05,
        upper=0.95,
    )
    data["factor_score"] = zscore_series(clipped)
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)


def score_dividend_growth_rank_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """使用无参数百分位排名映射分红增长下限。

    该版本保留相同有效性过滤，只替换最终分数映射，避免 TopN 与缩尾比例
    接近时大量头部股票被截成同一分数。
    """
    data = score_dividend_growth_frame(frame)
    if data.empty:
        return data
    data["factor_score"] = data["dividend_growth_floor"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
