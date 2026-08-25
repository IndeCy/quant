"""五年盈利底线因子。"""

from __future__ import annotations

import pandas as pd


def score_profitability_floor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """最差年度 ROA 越高，长期盈利韧性分数越高。"""
    required = ["symbol", "roa_floor_5y", "observations"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"profitability floor frame missing columns: {missing}")

    data = frame.copy()
    data["roa_floor_5y"] = pd.to_numeric(data["roa_floor_5y"], errors="coerce")
    data["observations"] = pd.to_numeric(data["observations"], errors="coerce")
    data = data[
        data["roa_floor_5y"].gt(0) & data["observations"].eq(5)
    ].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["roa_floor_5y"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
