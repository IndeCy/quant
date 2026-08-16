"""净经营资产异常因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_net_operating_assets(frame: pd.DataFrame) -> pd.DataFrame:
    """NOA率越低，资产负债表累积异常分数越高。"""
    required = {"symbol", "noa_ratio"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"net operating assets frame missing columns: {missing}")
    data = frame.copy()
    data["noa_ratio"] = pd.to_numeric(data["noa_ratio"], errors="coerce")
    data = data[np.isfinite(data["noa_ratio"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["noa_ratio"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
