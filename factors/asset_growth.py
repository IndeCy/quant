"""低资产增长投资因子。"""

from __future__ import annotations

import pandas as pd


def score_low_asset_growth_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """年度总资产增长越低，投资因子分数越高。"""
    required = ["symbol", "assets_yoy"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"asset growth frame missing columns: {missing}")
    data = frame.copy()
    data["assets_yoy"] = pd.to_numeric(data["assets_yoy"], errors="coerce")
    data = data[data["assets_yoy"].notna()].copy()
    if data.empty:
        return data.assign(
            assets_yoy_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )
    lower, upper = data["assets_yoy"].quantile([0.01, 0.99])
    data["assets_yoy_winsorized"] = data["assets_yoy"].clip(lower, upper)
    data["factor_score"] = data["assets_yoy_winsorized"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
