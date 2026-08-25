"""12-1月中期动量因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_intermediate_momentum(frame: pd.DataFrame) -> pd.DataFrame:
    """20至252交易日历史收益越高，动量分数越高。"""
    required = {"symbol", "intermediate_momentum"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"intermediate momentum frame missing columns: {missing}")
    data = frame.copy()
    data["intermediate_momentum"] = pd.to_numeric(
        data["intermediate_momentum"],
        errors="coerce",
    )
    data = data[np.isfinite(data["intermediate_momentum"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["intermediate_momentum"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
