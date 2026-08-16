"""放量下跌后的恐慌反转横截面因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_capitulation_reversal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """只保留放量下跌股票，跌幅和异常成交越大得分越高。"""
    required = ["return_20d", "abnormal_amount_ratio"]
    missing = [field for field in required if field not in frame.columns]
    if missing:
        raise ValueError(f"缺少恐慌反转字段: {missing}")
    data = frame.copy()
    data[required] = data[required].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(data[required]).all(axis=1)
    data = data[
        finite
        & data["return_20d"].lt(0)
        & data["abnormal_amount_ratio"].gt(1)
    ].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["loss_score"] = (-data["return_20d"]).rank(
        method="average",
        pct=True,
    )
    data["volume_score"] = data["abnormal_amount_ratio"].rank(
        method="average",
        pct=True,
    )
    data["factor_score"] = (
        data["loss_score"] + data["volume_score"]
    ) / 2.0
    return data
