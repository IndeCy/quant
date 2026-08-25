"""年度 ROA 改善因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_profitability_improvement(frame: pd.DataFrame) -> pd.DataFrame:
    """ROA 年度改善越大，横截面得分越高。"""
    required = {"symbol", "roa_change"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"profitability improvement missing columns: {missing}")
    data = frame.copy()
    data["roa_change"] = pd.to_numeric(data["roa_change"], errors="coerce")
    data = data[np.isfinite(data["roa_change"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["roa_change"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
