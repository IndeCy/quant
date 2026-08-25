"""Amihud 非流动性溢价因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_amihud_illiquidity_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """单位成交额价格冲击越高，非流动性溢价得分越高。"""
    required = ["symbol", "amihud_illiquidity", "observations"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"amihud illiquidity frame missing columns: {missing}")
    data = frame.copy()
    data["amihud_illiquidity"] = pd.to_numeric(
        data["amihud_illiquidity"],
        errors="coerce",
    )
    data["observations"] = pd.to_numeric(data["observations"], errors="coerce")
    finite = (
        data["amihud_illiquidity"].notna()
        & np.isfinite(data["amihud_illiquidity"])
        & data["amihud_illiquidity"].gt(0)
    )
    data = data[finite & data["observations"].eq(60)].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["amihud_illiquidity"].rank(
        method="average",
        pct=True,
    )
    return data
