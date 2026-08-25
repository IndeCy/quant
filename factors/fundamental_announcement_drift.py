"""季度财报公告后基本面漂移因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.quality import winsorize_series, zscore_series


def score_fundamental_announcement_drift_frame(
    frame: pd.DataFrame,
    *,
    require_cash_quality: bool = True,
) -> pd.DataFrame:
    """打分公告后90日内收入和利润同步增长的盈利公司。"""
    required = [
        "symbol",
        "signal_date",
        "f_ann_date",
        "roa",
        "ocf_to_or",
        "netprofit_yoy",
        "tr_yoy",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"announcement drift frame missing columns: {missing}")

    data = frame.copy()
    numeric = ["roa", "ocf_to_or", "netprofit_yoy", "tr_yoy"]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    signal_dates = pd.to_datetime(data["signal_date"], format="%Y%m%d", errors="coerce")
    announcement_dates = pd.to_datetime(
        data["f_ann_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    data["announcement_age_days"] = (signal_dates - announcement_dates).dt.days
    valid = (
        np.isfinite(data[numeric]).all(axis=1)
        & data["announcement_age_days"].between(0, 90, inclusive="both")
        & data["roa"].gt(0)
        & data["netprofit_yoy"].gt(0)
        & data["tr_yoy"].gt(0)
    )
    if require_cash_quality:
        valid &= data["ocf_to_or"].gt(0)
    data = data[valid].copy()
    score_columns = ["netprofit_yoy", "tr_yoy"]
    if require_cash_quality:
        score_columns.append("ocf_to_or")
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))

    score_parts: list[pd.Series] = []
    for column in score_columns:
        score_parts.append(
            zscore_series(
                winsorize_series(data[column], lower=0.05, upper=0.95)
            )
        )
    data["factor_score"] = sum(score_parts) / len(score_parts)
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
