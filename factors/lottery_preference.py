"""低 MAX 彩票偏好因子。"""

from __future__ import annotations

import pandas as pd


def score_low_max_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """最大单日收益越低，彩票偏好暴露越弱，分数越高。"""
    required = ["symbol", "max_ret20"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"lottery preference frame missing columns: {missing}")

    data = frame.copy()
    data["max_ret20"] = pd.to_numeric(data["max_ret20"], errors="coerce")
    data = data[data["max_ret20"].notna()].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))

    # 日收益天然受涨跌停约束，直接分位排名，避免缩尾制造头部并列。
    data["factor_score"] = data["max_ret20"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
