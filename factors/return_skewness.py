"""低收益偏度行为因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_low_return_skewness_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """过去60日收益偏度越低，彩票型暴露越弱，得分越高。"""
    field = "return_skewness_60d"
    required = ["symbol", field]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"return skewness frame missing columns: {missing}")
    data = frame.copy()
    values = pd.to_numeric(data[field], errors="coerce")
    valid = values.notna() & np.isfinite(values)
    data = data.loc[valid].copy()
    data[field] = values.loc[valid]
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    # 直接使用横截面秩，避免缩尾在TopN边界制造大面积并列。
    data["factor_score"] = data[field].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
