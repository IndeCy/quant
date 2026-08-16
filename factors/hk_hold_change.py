"""北向个股持仓占比变化因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_hk_hold_change_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """相邻月末北向持仓占比增加越多，得分越高。"""
    required = [
        "symbol",
        "holding_ratio_change",
        "current_holding_ratio",
        "prior_holding_ratio",
        "period_gap_days",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"hk hold change frame missing columns: {missing}")
    data = frame.copy()
    for column in required[1:]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    finite = np.isfinite(data["holding_ratio_change"])
    data = data[
        finite
        & data["holding_ratio_change"].gt(0.0)
        & data["current_holding_ratio"].between(0.0, 100.0)
        & data["prior_holding_ratio"].between(0.0, 100.0)
        & data["period_gap_days"].between(20, 45)
    ].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["holding_ratio_change"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
