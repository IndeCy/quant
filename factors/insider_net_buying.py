"""高管与个人股东净增持因子。"""

from __future__ import annotations

import pandas as pd


def score_insider_net_buying_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """只保留净增持股票，净增持流通股比例越高得分越高。"""
    required = ["symbol", "net_buy_ratio"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"insider net buying frame missing columns: {missing}")

    data = frame.copy()
    data["net_buy_ratio"] = pd.to_numeric(data["net_buy_ratio"], errors="coerce")
    data = data[data["net_buy_ratio"].gt(0)].copy()
    if data.empty:
        return data.assign(
            net_buy_ratio_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )
    lower, upper = data["net_buy_ratio"].quantile([0.01, 0.99])
    data["net_buy_ratio_winsorized"] = data["net_buy_ratio"].clip(lower, upper)
    data["factor_score"] = data["net_buy_ratio_winsorized"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
