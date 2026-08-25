"""大单与特大单净流入强度因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


MIN_OBSERVATIONS = 15


def score_large_order_flow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """只保留持续正向且观测充分的真实大单净流入。"""
    required = ["symbol", "large_order_net_share", "observations"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"large order flow frame missing columns: {missing}")
    data = frame.copy()
    data["large_order_net_share"] = pd.to_numeric(
        data["large_order_net_share"],
        errors="coerce",
    )
    data["observations"] = pd.to_numeric(data["observations"], errors="coerce")
    valid = (
        data["observations"].ge(MIN_OBSERVATIONS)
        & data["large_order_net_share"].gt(0)
        & data["large_order_net_share"].between(-1.0, 1.0)
        & np.isfinite(data["large_order_net_share"])
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["large_order_net_share"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
