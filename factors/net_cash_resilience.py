"""净现金财务韧性因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_net_cash_resilience_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """净现金资产比越高，财务韧性得分越高。"""
    required = [
        "symbol",
        "net_cash_to_assets",
        "reported_debt_item_count",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"net cash frame missing columns: {missing}")

    data = frame.copy()
    data["net_cash_to_assets"] = pd.to_numeric(
        data["net_cash_to_assets"],
        errors="coerce",
    )
    data["reported_debt_item_count"] = pd.to_numeric(
        data["reported_debt_item_count"],
        errors="coerce",
    )
    valid = (
        data["net_cash_to_assets"].notna()
        & np.isfinite(data["net_cash_to_assets"])
        & data["net_cash_to_assets"].between(-5.0, 1.05)
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["net_cash_to_assets"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
