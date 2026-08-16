"""低特质波动率因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_low_residual_volatility_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """市场模型残差波动越低，横截面因子分数越高。"""
    required = ["symbol", "residual_volatility"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"residual volatility frame missing columns: {missing}")
    data = frame.copy()
    data["residual_volatility"] = pd.to_numeric(
        data["residual_volatility"],
        errors="coerce",
    ).replace([np.inf, -np.inf], np.nan)
    data = data.dropna(subset=["residual_volatility"])
    data = data[data["residual_volatility"].ge(0)].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["residual_volatility"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
