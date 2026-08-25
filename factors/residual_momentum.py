"""走步双因子残差动量评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_residual_momentum(frame: pd.DataFrame) -> pd.DataFrame:
    """历史特质收益累计越高，横截面分数越高。"""
    required = {"symbol", "residual_momentum"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"residual momentum frame missing columns: {missing}")
    data = frame.copy()
    data["residual_momentum"] = pd.to_numeric(
        data["residual_momentum"],
        errors="coerce",
    )
    data = data[np.isfinite(data["residual_momentum"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["residual_momentum"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
