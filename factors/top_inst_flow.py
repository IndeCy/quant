"""机构席位净买入强度因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_top_inst_flow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """按近20日机构净买入占平均成交额比例生成横截面得分。"""
    required = ["symbol", "total_net_buy", "adv_rmb"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"top_inst flow frame missing columns: {missing}")
    data = frame.copy()
    data["total_net_buy"] = pd.to_numeric(
        data["total_net_buy"],
        errors="coerce",
    )
    data["adv_rmb"] = pd.to_numeric(data["adv_rmb"], errors="coerce")
    data["net_buy_to_adv"] = data["total_net_buy"] / data["adv_rmb"]
    valid = (
        data["total_net_buy"].gt(0)
        & data["adv_rmb"].gt(0)
        & np.isfinite(data["net_buy_to_adv"])
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["net_buy_to_adv"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
