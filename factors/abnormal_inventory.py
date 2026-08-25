"""异常存货积累横截面因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_abnormal_inventory_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """存货相对销售积累越少，因子得分越高。"""
    field = "abnormal_inventory_accumulation"
    required = ["symbol", field]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"abnormal inventory frame missing columns: {missing}")
    data = frame.copy()
    values = pd.to_numeric(data[field], errors="coerce")
    valid = values.notna() & np.isfinite(values)
    data = data.loc[valid].copy()
    data[field] = values.loc[valid]
    if data.empty:
        return data.assign(
            abnormal_inventory_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )
    lower, upper = data[field].quantile([0.01, 0.99])
    data["abnormal_inventory_winsorized"] = data[field].clip(lower, upper)
    data["factor_score"] = data[
        "abnormal_inventory_winsorized"
    ].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
