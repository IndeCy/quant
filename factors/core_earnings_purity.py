"""核心利润纯度因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.quality import winsorize_series


def score_core_earnings_purity_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """按扣非利润占净利润比例生成高值优先的横截面得分。"""
    required = {"symbol", "dtprofit_to_profit"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"核心利润纯度缺少字段: {missing}")

    scored = frame.copy()
    scored["dtprofit_to_profit"] = pd.to_numeric(
        scored["dtprofit_to_profit"],
        errors="coerce",
    ).replace([np.inf, -np.inf], np.nan)
    scored = scored.dropna(subset=["dtprofit_to_profit"]).copy()
    if scored.empty:
        return scored.assign(factor_score=pd.Series(dtype=float))

    # 比例容易受接近零的利润分母影响，先做固定横截面缩尾再排名。
    clipped = winsorize_series(
        scored["dtprofit_to_profit"],
        lower=0.01,
        upper=0.99,
    )
    scored["factor_score"] = clipped.rank(
        method="average",
        pct=True,
        ascending=True,
    )
    return scored.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
    ).reset_index(drop=True)
