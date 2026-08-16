"""Quality ML 的时点安全特征预处理。"""

from __future__ import annotations

import pandas as pd

from factors.quality import QUALITY_COLUMNS, winsorize_series, zscore_series


MODEL_FEATURES = tuple(f"{column}_z" for column in QUALITY_COLUMNS)


def build_cross_section_features(frame: pd.DataFrame) -> pd.DataFrame:
    """每个信号日独立缩尾和标准化，不跨时间借用统计量。"""
    required = ["signal_date", *QUALITY_COLUMNS]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"ML feature frame missing columns: {missing}")
    result = frame.copy()
    for column in QUALITY_COLUMNS:
        result[f"{column}_z"] = result.groupby("signal_date", group_keys=False)[column].transform(
            lambda values: zscore_series(winsorize_series(values))
        )
    return result


def monthly_equal_sample_weights(frame: pd.DataFrame) -> pd.Series:
    """让每个调仓月总权重相等，避免股票数量增长支配训练。"""
    if "signal_date" not in frame.columns:
        raise ValueError("sample frame missing signal_date")
    counts = frame.groupby("signal_date")["signal_date"].transform("size")
    if counts.empty or counts.le(0).any():
        raise ValueError("invalid monthly sample counts")
    weights = 1.0 / counts.astype(float)
    return weights / weights.mean()
