"""一般工商业净债务融资因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_net_debt_financing_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """净债务融资越低、净偿债越多，横截面分数越高。"""
    required = ["symbol", "net_debt_financing"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"net debt financing frame missing columns: {missing}")
    data = frame.copy()
    data["net_debt_financing"] = pd.to_numeric(
        data["net_debt_financing"],
        errors="coerce",
    )
    data = data[np.isfinite(data["net_debt_financing"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["net_debt_financing"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
