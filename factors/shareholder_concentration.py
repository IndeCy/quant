"""股东户数下降形成的筹码集中因子。"""

from __future__ import annotations

import pandas as pd


def score_shareholder_concentration_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """筹码集中速度越高，因子分数越高。"""
    required = ["symbol", "concentration_rate_90d"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"shareholder concentration frame missing columns: {missing}")

    data = frame.copy()
    data["concentration_rate_90d"] = pd.to_numeric(
        data["concentration_rate_90d"],
        errors="coerce",
    )
    data = data[data["concentration_rate_90d"].notna()].copy()
    if data.empty:
        return data.assign(
            concentration_rate_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )
    lower, upper = data["concentration_rate_90d"].quantile([0.01, 0.99])
    data["concentration_rate_winsorized"] = data[
        "concentration_rate_90d"
    ].clip(lower, upper)
    data["factor_score"] = data["concentration_rate_winsorized"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
