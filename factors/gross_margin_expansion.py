"""连续年报毛利率改善因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.quality import winsorize_series


def score_gross_margin_expansion_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """毛利率同比改善幅度越大，横截面分数越高。"""
    required = ["symbol", "gross_margin_change"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"gross margin frame missing columns: {missing}")
    data = frame.copy()
    data["gross_margin_change"] = pd.to_numeric(
        data["gross_margin_change"],
        errors="coerce",
    )
    data = data[np.isfinite(data["gross_margin_change"])].copy()
    if data.empty:
        return data.assign(
            gross_margin_change_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )
    data["gross_margin_change_winsorized"] = winsorize_series(
        data["gross_margin_change"],
        lower=0.01,
        upper=0.99,
    )
    data["factor_score"] = data["gross_margin_change_winsorized"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data


def score_gross_margin_expansion_rank_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """直接按原始改善幅度排名，避免单因子截尾造成TopN大面积并列。"""
    required = ["symbol", "gross_margin_change"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"gross margin frame missing columns: {missing}")
    data = frame.copy()
    data["gross_margin_change"] = pd.to_numeric(
        data["gross_margin_change"],
        errors="coerce",
    )
    data = data[np.isfinite(data["gross_margin_change"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["gross_margin_change"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
