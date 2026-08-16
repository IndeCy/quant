"""业绩预告确定性动量因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.quality import winsorize_series, zscore_series


POSITIVE_FORECAST_TYPES = frozenset({"预增", "略增", "续盈"})


def score_earnings_forecast_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """按正向业绩预告增幅中值计算横截面分数。

    上下限都大于零用于排除方向不确定的预告，预增、略增和续盈用于排除
    扭亏及续亏的低基数干扰。函数只计算分数，不决定组合权重。
    """
    required = [
        "symbol",
        "signal_date",
        "publish_date",
        "forecast_type",
        "p_change_min",
        "p_change_max",
        "p_change_mid",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"earnings forecast frame missing columns: {missing}")

    data = frame.copy()
    numeric = ["p_change_min", "p_change_max", "p_change_mid"]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    valid = (
        np.isfinite(data[numeric]).all(axis=1)
        & data["forecast_type"].isin(POSITIVE_FORECAST_TYPES)
        & data["p_change_min"].gt(0)
        & data["p_change_max"].gt(0)
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))

    clipped = winsorize_series(data["p_change_mid"], lower=0.05, upper=0.95)
    data["factor_score"] = zscore_series(clipped)
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
