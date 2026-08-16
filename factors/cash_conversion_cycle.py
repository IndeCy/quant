"""现金转换周期改善的横截面因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_cash_conversion_cycle_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """周期缩短越多分数越高，缺失或非有限值不得进入排序。"""
    field = "cash_conversion_cycle_change"
    if field not in frame.columns:
        raise ValueError(f"缺少 {field} 字段")
    data = frame.copy()
    values = pd.to_numeric(data[field], errors="coerce")
    finite = values.notna() & np.isfinite(values)
    data = data.loc[finite].copy()
    data[field] = values.loc[finite]
    data["factor_score"] = data[field].rank(
        method="average",
        pct=True,
        ascending=False,
    )
    return data
