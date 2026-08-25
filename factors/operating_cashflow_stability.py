"""五年经营现金流稳定性因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_operating_cashflow_stability(frame: pd.DataFrame) -> pd.DataFrame:
    """排除长期现金流为负的公司，并让低 OCF 波动获得高分。"""
    required = {
        "symbol",
        "ocf_assets_median_5y",
        "ocf_assets_std_5y",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"operating cashflow frame missing columns: {missing}")
    data = frame.copy()
    for column in ("ocf_assets_median_5y", "ocf_assets_std_5y"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = (
        np.isfinite(
            data[["ocf_assets_median_5y", "ocf_assets_std_5y"]]
        ).all(axis=1)
        & data["ocf_assets_median_5y"].gt(0)
        & data["ocf_assets_std_5y"].ge(0)
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["ocf_assets_std_5y"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
