"""日内强度减隔夜情绪因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_intraday_strength_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """盘中持续买盘相对隔夜情绪越强，横截面分数越高。"""
    required = ["symbol", "intraday_strength"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"intraday strength frame missing columns: {missing}")
    data = frame.copy()
    data["intraday_strength"] = pd.to_numeric(
        data["intraday_strength"],
        errors="coerce",
    ).replace([np.inf, -np.inf], np.nan)
    data = data.dropna(subset=["intraday_strength"]).copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["intraday_strength"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
