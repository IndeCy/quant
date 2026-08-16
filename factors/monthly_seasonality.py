"""跨年月份季节性因子。"""

from __future__ import annotations

import pandas as pd


def score_monthly_seasonality_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """历史同月平均收益越高，季节性分数越高。"""
    required = ["symbol", "seasonal_mean_return", "observations"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"monthly seasonality frame missing columns: {missing}")

    data = frame.copy()
    data["seasonal_mean_return"] = pd.to_numeric(
        data["seasonal_mean_return"],
        errors="coerce",
    )
    data["observations"] = pd.to_numeric(data["observations"], errors="coerce")
    data = data[
        data["seasonal_mean_return"].notna() & data["observations"].ge(3)
    ].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["seasonal_mean_return"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
