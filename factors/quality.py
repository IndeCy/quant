"""Quality Alpha 使用的标准财务因子变换。"""

from __future__ import annotations

import pandas as pd


QUALITY_COLUMNS = ["roe", "roa", "ocf_to_or"]
ATTRIBUTION_COLUMNS = ["roe", "roa", "debt_to_assets", "tr_yoy"]


def winsorize_series(
    series: pd.Series,
    lower: float = 0.05,
    upper: float = 0.95,
) -> pd.Series:
    """按横截面分位缩尾，避免单个异常财务值主导分数。"""
    if not 0 <= lower < upper <= 1:
        raise ValueError("winsorize quantiles must satisfy 0 <= lower < upper <= 1")
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.clip(numeric.quantile(lower), numeric.quantile(upper))


def zscore_series(series: pd.Series) -> pd.Series:
    """使用总体标准差计算横截面 Z-score。"""
    numeric = pd.to_numeric(series, errors="coerce")
    standard_deviation = numeric.std(ddof=0)
    if pd.isna(standard_deviation) or standard_deviation == 0:
        return pd.Series(0.0, index=series.index)
    return (numeric - numeric.mean()) / standard_deviation


def score_quality_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """复现 Quality V1 的缩尾、标准化和三因子等权得分。"""
    missing = [column for column in ["symbol", *QUALITY_COLUMNS] if column not in frame.columns]
    if missing:
        raise ValueError(f"quality frame missing columns: {missing}")
    scored = frame.dropna(subset=QUALITY_COLUMNS).copy()
    for column in QUALITY_COLUMNS:
        scored[f"{column}_z"] = zscore_series(winsorize_series(scored[column]))
    score_columns = [f"{column}_z" for column in QUALITY_COLUMNS]
    scored["quality_score"] = scored[score_columns].mean(axis=1)
    return scored.sort_values(
        ["quality_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
