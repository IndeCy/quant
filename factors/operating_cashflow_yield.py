"""点时经营现金流收益率因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_operating_cashflow_yield(frame: pd.DataFrame) -> pd.DataFrame:
    """仅保留正现金流收益率，并按横截面百分位升序评分。"""
    required = {"symbol", "operating_cashflow_yield"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            f"operating cashflow yield frame missing columns: {missing}"
        )
    data = frame.copy()
    data["operating_cashflow_yield"] = pd.to_numeric(
        data["operating_cashflow_yield"],
        errors="coerce",
    )
    valid = (
        np.isfinite(data["operating_cashflow_yield"])
        & data["operating_cashflow_yield"].gt(0)
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["operating_cashflow_yield"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
