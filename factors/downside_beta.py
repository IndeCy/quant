"""低下行 Beta 防御因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_downside_beta_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """在合理的正向权益 Beta 范围内，下行 Beta 越低得分越高。"""
    required = [
        "symbol",
        "downside_beta",
        "total_beta",
        "observations",
        "downside_observations",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"downside beta frame missing columns: {missing}")

    data = frame.copy()
    for column in required[1:]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    finite = (
        np.isfinite(data["downside_beta"])
        & np.isfinite(data["total_beta"])
    )
    # 长仓研究只保留具有正常正向市场暴露的股票，排除噪声型负 Beta。
    data = data[
        finite
        & data["downside_beta"].between(0.0, 3.0)
        & data["total_beta"].between(0.0, 3.0)
        & data["observations"].ge(200)
        & data["downside_observations"].ge(60)
    ].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["downside_beta"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
