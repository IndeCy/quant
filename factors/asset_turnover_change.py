"""资产周转率改善的横截面因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_asset_turnover_change_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """按原始连续变化值排名，改善越大分数越高。"""
    if "asset_turnover_change" not in frame.columns:
        raise ValueError("缺少 asset_turnover_change 字段")
    data = frame.copy()
    values = pd.to_numeric(data["asset_turnover_change"], errors="coerce")
    finite = values.notna() & np.isfinite(values)
    data = data.loc[finite].copy()
    data["asset_turnover_change"] = values.loc[finite]
    data["factor_score"] = data["asset_turnover_change"].rank(
        method="average",
        pct=True,
    )
    return data
