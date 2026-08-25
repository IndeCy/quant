"""点时盈利收益率因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_earnings_yield(frame: pd.DataFrame) -> pd.DataFrame:
    """只保留正盈利收益率，并让高 E/P 获得高分。"""
    required = {"symbol", "earnings_yield"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"earnings yield frame missing columns: {missing}")
    data = frame.copy()
    data["earnings_yield"] = pd.to_numeric(
        data["earnings_yield"],
        errors="coerce",
    )
    valid = (
        np.isfinite(data["earnings_yield"])
        & data["earnings_yield"].gt(0)
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["earnings_yield"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
