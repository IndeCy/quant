"""长期趋势过滤后的短期反转横截面打分。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.quality import winsorize_series, zscore_series


def score_trend_filtered_reversal_frame(
    frame: pd.DataFrame,
    *,
    require_positive_trend: bool = True,
) -> pd.DataFrame:
    """选择长期趋势未破坏、近20日温和回撤的股票。

    `require_positive_trend=False` 只用于归因对照，主策略始终开启趋势过滤。
    """
    required = ["symbol", "ret20", "ret120", "close", "ma60", "ma120"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"trend reversal frame missing columns: {missing}")

    data = frame.copy()
    numeric = ["ret20", "ret120", "close", "ma60", "ma120"]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    valid = (
        np.isfinite(data[numeric]).all(axis=1)
        & data["close"].gt(0)
        & data["ma60"].gt(0)
        & data["ma120"].gt(0)
        & data["ret20"].ge(-0.20)
        & data["ret20"].lt(0)
    )
    if require_positive_trend:
        valid &= (
            data["ret120"].gt(0)
            & data["close"].gt(data["ma120"])
            & data["ma60"].gt(data["ma120"])
        )
    data = data[valid].copy()
    if data.empty:
        return data.assign(
            pullback_score=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )

    data["pullback_score"] = zscore_series(
        winsorize_series(-data["ret20"], lower=0.01, upper=0.99)
    )
    data["factor_score"] = data["pullback_score"]
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
