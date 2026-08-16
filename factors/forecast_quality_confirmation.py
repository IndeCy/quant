"""业绩预告与 Quality 等权确认评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_forecast_quality_confirmation(frame: pd.DataFrame) -> pd.DataFrame:
    """将预告强度和 Quality 强度的横截面秩各赋 50% 权重。"""
    required = {"symbol", "forecast_score", "quality_score"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"forecast quality frame missing columns: {missing}")
    data = frame.copy()
    numeric = ["forecast_score", "quality_score"]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    data = data[np.isfinite(data[numeric]).all(axis=1)].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["forecast_rank"] = data["forecast_score"].rank(
        method="average",
        pct=True,
    )
    data["quality_rank"] = data["quality_score"].rank(
        method="average",
        pct=True,
    )
    data["factor_score"] = (
        data["forecast_rank"] * 0.5 + data["quality_rank"] * 0.5
    )
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
