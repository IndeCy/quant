"""价格路径连续性动量因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_smooth_momentum_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """正中期收益越高且上涨路径越连续，横截面得分越高。"""
    required = [
        "symbol",
        "momentum_skip_recent",
        "path_continuity",
        "smooth_momentum",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"smooth momentum frame missing columns: {missing}")
    data = frame.copy()
    data[required[1:]] = data[required[1:]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    finite = np.isfinite(data[required[1:]]).all(axis=1)
    data = data[finite & data["momentum_skip_recent"].gt(0)].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["smooth_momentum"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
