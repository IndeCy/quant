"""五年盈利稳定性因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_earnings_stability_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """五年 ROA 波动越小，盈利稳定性得分越高。"""
    required = ["symbol", "roa_std_5y", "roa_mean_5y", "observations"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"earnings stability frame missing columns: {missing}")

    data = frame.copy()
    for column in ["roa_std_5y", "roa_mean_5y", "observations"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    finite = (
        data["roa_std_5y"].notna()
        & np.isfinite(data["roa_std_5y"])
        & data["roa_std_5y"].ge(0)
    )
    # 正平均盈利只用于排除“稳定亏损”，不要求较高 ROA 水平。
    data = data[
        finite
        & data["roa_mean_5y"].gt(0)
        & data["observations"].eq(5)
    ].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["roa_std_5y"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
