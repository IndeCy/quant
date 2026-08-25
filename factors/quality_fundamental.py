"""盈利质量与资产负债表因子的统一横截面打分。"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from factors.quality import winsorize_series, zscore_series


def score_quality_fundamental_frame(
    frame: pd.DataFrame,
    factor_directions: Mapping[str, int],
) -> pd.DataFrame:
    """按固定方向对因子做1%/99%缩尾、Z-score和等权合成。"""
    if not factor_directions:
        raise ValueError("factor_directions cannot be empty")
    invalid = {
        factor: direction
        for factor, direction in factor_directions.items()
        if direction not in {-1, 1}
    }
    if invalid:
        raise ValueError(f"factor directions must be -1 or 1: {invalid}")
    required = ["symbol", *factor_directions]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"quality fundamental frame missing columns: {missing}")

    scored = frame.dropna(subset=list(factor_directions)).copy()
    score_columns: list[str] = []
    for factor, direction in factor_directions.items():
        column = f"{factor}_z"
        standardized = zscore_series(
            winsorize_series(scored[factor], lower=0.01, upper=0.99)
        )
        scored[column] = standardized * direction
        score_columns.append(column)
    scored["factor_score"] = scored[score_columns].mean(axis=1)
    return scored.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
