"""52 周最高收盘接近度因子。"""

from __future__ import annotations

import pandas as pd


def score_price_high_proximity_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """价格越接近过去 252 个交易日最高收盘，因子分数越高。"""
    required = ["symbol", "high_proximity"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"price high frame missing columns: {missing}")
    data = frame.copy()
    data["high_proximity"] = pd.to_numeric(
        data["high_proximity"],
        errors="coerce",
    )
    data = data[data["high_proximity"].between(0, 1, inclusive="both")].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["high_proximity"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data


def score_price_high_breakout_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """相对前 252 日最高收盘的突破越强，横截面分数越高。"""
    required = ["symbol", "breakout_strength"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"price breakout frame missing columns: {missing}")
    data = frame.copy()
    data["breakout_strength"] = pd.to_numeric(
        data["breakout_strength"],
        errors="coerce",
    )
    data = data[data["breakout_strength"].gt(0)].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["breakout_strength"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
