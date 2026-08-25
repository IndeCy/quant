"""成交额加权涨跌压力因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_signed_amount_pressure_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """持续正向成交额压力越高，横截面得分越高。"""
    field = "signed_amount_pressure"
    if field not in frame.columns:
        raise ValueError(f"缺少 {field} 字段")
    data = frame.copy()
    values = pd.to_numeric(data[field], errors="coerce")
    finite = values.notna() & np.isfinite(values) & values.between(-1, 1)
    data = data.loc[finite].copy()
    data[field] = values.loc[finite]
    data["factor_score"] = data[field].rank(
        method="average",
        pct=True,
    )
    return data
