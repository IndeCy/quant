"""年度去杠杆变化因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_deleveraging_change(frame: pd.DataFrame) -> pd.DataFrame:
    """资产负债率下降越多，去杠杆分数越高。"""
    required = {"symbol", "debt_to_assets_change"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"deleveraging frame missing columns: {missing}")
    data = frame.copy()
    data["debt_to_assets_change"] = pd.to_numeric(
        data["debt_to_assets_change"],
        errors="coerce",
    )
    data = data[np.isfinite(data["debt_to_assets_change"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["debt_to_assets_change"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
