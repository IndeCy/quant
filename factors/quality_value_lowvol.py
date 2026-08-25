"""Quality、估值与低波因子的统一横截面变换。"""

from __future__ import annotations

import math

import pandas as pd

from factors.quality import winsorize_series, zscore_series


FACTOR_COLUMNS = (
    "roa",
    "ocf_to_or",
    "earnings_yield",
    "book_yield",
    "low_volatility_60d",
)


def score_quality_value_lowvol_frame(
    frame: pd.DataFrame,
    factor_weights: dict[str, float],
) -> pd.DataFrame:
    """按 1%/99% 缩尾、Z-score 和声明权重计算组合分数。"""
    required = ["symbol", *FACTOR_COLUMNS]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"quality value lowvol frame missing columns: {missing}")
    _validate_weights(factor_weights)
    scored = frame.dropna(subset=list(FACTOR_COLUMNS)).copy()
    for column in FACTOR_COLUMNS:
        scored[f"{column}_z"] = zscore_series(
            winsorize_series(scored[column], lower=0.01, upper=0.99)
        )
    scored["factor_score"] = sum(
        scored[f"{factor_id}_z"] * factor_weights[factor_id]
        for factor_id in FACTOR_COLUMNS
    )
    return scored.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)


def _validate_weights(factor_weights: dict[str, float]) -> None:
    """生产策略必须显式声明且只声明当前冻结的五个因子。"""
    if set(factor_weights) != set(FACTOR_COLUMNS):
        raise ValueError("quality value lowvol factor set must match the frozen five-factor contract")
    values = [float(factor_weights[factor_id]) for factor_id in FACTOR_COLUMNS]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("factor weights must be finite and non-negative")
    if not math.isclose(sum(values), 1.0, abs_tol=1e-9):
        raise ValueError("factor weights must sum to 1")
