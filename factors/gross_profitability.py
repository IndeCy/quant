"""毛利润相对总资产的盈利能力因子。"""

from __future__ import annotations

import pandas as pd


def score_gross_profitability_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """毛利率乘资产周转率越高，Gross Profitability 得分越高。"""
    required = ["symbol", "grossprofit_margin", "assets_turn"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"gross profitability frame missing columns: {missing}")
    data = frame.copy()
    for column in ["grossprofit_margin", "assets_turn"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["grossprofit_margin", "assets_turn"]).copy()
    data["gross_profitability"] = (
        data["grossprofit_margin"] * data["assets_turn"]
    )
    data = data[data["gross_profitability"].notna()].copy()
    if data.empty:
        return data.assign(
            gross_profitability_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )
    lower, upper = data["gross_profitability"].quantile([0.01, 0.99])
    data["gross_profitability_winsorized"] = data["gross_profitability"].clip(
        lower,
        upper,
    )
    data["factor_score"] = data["gross_profitability_winsorized"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
