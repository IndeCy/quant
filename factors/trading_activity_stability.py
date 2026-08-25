"""交易活跃度稳定性因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_trading_activity_stability(frame: pd.DataFrame) -> pd.DataFrame:
    """滚动对数成交额波动越低，稳定性分数越高。"""
    required = {"symbol", "activity_volatility"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"trading activity frame missing columns: {missing}")
    data = frame.copy()
    data["activity_volatility"] = pd.to_numeric(
        data["activity_volatility"],
        errors="coerce",
    )
    data = data[
        np.isfinite(data["activity_volatility"])
        & data["activity_volatility"].ge(0)
    ].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["activity_volatility"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
