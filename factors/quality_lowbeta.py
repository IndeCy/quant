"""Quality LowBeta 固定四因子横截面评分。"""

from __future__ import annotations

import pandas as pd

from factors.quality import winsorize_series, zscore_series


FACTOR_COLUMNS = ("roa", "ocf_to_or", "low_beta_120d", "low_volatility_60d")


def score_quality_lowbeta_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """按 1%/99% 缩尾、Z-score 和四因子等权计算得分。"""
    missing = [column for column in ["symbol", *FACTOR_COLUMNS] if column not in frame.columns]
    if missing:
        raise ValueError(f"quality lowbeta frame missing columns: {missing}")
    scored = frame.dropna(subset=list(FACTOR_COLUMNS)).copy()
    for column in FACTOR_COLUMNS:
        scored[f"{column}_z"] = zscore_series(
            winsorize_series(scored[column], lower=0.01, upper=0.99)
        )
    scored["factor_score"] = scored[[f"{column}_z" for column in FACTOR_COLUMNS]].mean(axis=1)
    return scored.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
