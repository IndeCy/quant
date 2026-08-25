"""Tushare源净流入占成交额因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


MIN_OBSERVATIONS = 15


def score_source_net_moneyflow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """按官方净流入占成交额比例排序，只保留正向且观测充分的股票。"""
    required = ["symbol", "source_net_turnover_share", "observations"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"source net moneyflow frame missing columns: {missing}")
    data = frame.copy()
    data["source_net_turnover_share"] = pd.to_numeric(
        data["source_net_turnover_share"],
        errors="coerce",
    )
    data["observations"] = pd.to_numeric(data["observations"], errors="coerce")
    valid = (
        data["observations"].ge(MIN_OBSERVATIONS)
        & data["source_net_turnover_share"].gt(0)
        & data["source_net_turnover_share"].between(-1.0, 1.0)
        & np.isfinite(data["source_net_turnover_share"])
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["source_net_turnover_share"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
