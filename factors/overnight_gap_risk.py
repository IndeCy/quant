"""低隔夜跳空风险因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_overnight_gap_risk(frame: pd.DataFrame) -> pd.DataFrame:
    """60日隔夜收益波动越低，防御分数越高。"""
    required = {"symbol", "overnight_volatility"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"overnight gap risk frame missing columns: {missing}")
    data = frame.copy()
    data["overnight_volatility"] = pd.to_numeric(
        data["overnight_volatility"],
        errors="coerce",
    )
    data = data[
        np.isfinite(data["overnight_volatility"])
        & data["overnight_volatility"].ge(0)
    ].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["overnight_volatility"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
