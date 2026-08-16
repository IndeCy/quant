"""Fama-French 经营盈利能力因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_operating_profitability_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """经营盈利能力越高，横截面分数越高。"""
    required = ["symbol", "operating_profitability"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"operating profitability frame missing columns: {missing}")
    data = frame.copy()
    data["operating_profitability"] = pd.to_numeric(
        data["operating_profitability"],
        errors="coerce",
    )
    data = data[np.isfinite(data["operating_profitability"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    # 原始秩对极端值不敏感，也不会像截尾那样制造顶部大面积并列。
    data["factor_score"] = data["operating_profitability"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
