"""大宗交易金额加权溢价因子。"""

from __future__ import annotations

import pandas as pd


def score_block_trade_premium_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """只保留正溢价股票，金额加权溢价越高得分越高。"""
    required = ["symbol", "amount_weighted_premium"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"block trade premium frame missing columns: {missing}")
    data = frame.copy()
    data["amount_weighted_premium"] = pd.to_numeric(
        data["amount_weighted_premium"],
        errors="coerce",
    )
    data = data[data["amount_weighted_premium"].gt(0)].copy()
    if data.empty:
        return data.assign(
            premium_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )
    lower, upper = data["amount_weighted_premium"].quantile([0.01, 0.99])
    data["premium_winsorized"] = data["amount_weighted_premium"].clip(lower, upper)
    data["factor_score"] = data["premium_winsorized"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
