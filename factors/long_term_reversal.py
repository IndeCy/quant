"""长期反转因子评分。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_long_term_reversal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """36 至 13 个月历史收益越低，反转分数越高。"""
    required = {"symbol", "long_term_return"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"long term reversal frame missing columns: {missing}")
    data = frame.copy()
    data["long_term_return"] = pd.to_numeric(
        data["long_term_return"],
        errors="coerce",
    )
    data = data[np.isfinite(data["long_term_return"])].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["long_term_return"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
