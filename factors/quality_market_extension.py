"""在冻结Quality V1分数上叠加少量市场行为因子。"""

from __future__ import annotations

from collections.abc import Mapping
import math

import pandas as pd

from factors.quality import score_quality_frame, winsorize_series, zscore_series


def score_quality_market_extension(
    frame: pd.DataFrame,
    extension_weights: Mapping[str, float],
) -> pd.DataFrame:
    """保留Quality V1主体，以声明权重加入1%/99%缩尾的增强因子。"""
    weights = {factor: float(weight) for factor, weight in extension_weights.items()}
    total_extension = sum(weights.values())
    if (
        not weights
        or any(not math.isfinite(weight) or weight <= 0 for weight in weights.values())
        or total_extension >= 1
    ):
        raise ValueError("extension weights must be positive and sum to less than 1")
    missing = [factor for factor in weights if factor not in frame.columns]
    if missing:
        raise ValueError(f"quality market extension missing columns: {missing}")

    scored = score_quality_frame(frame)
    scored = scored.dropna(subset=list(weights)).copy()
    scored["factor_score"] = scored["quality_score"] * (1.0 - total_extension)
    for factor, weight in weights.items():
        column = f"{factor}_z"
        scored[column] = zscore_series(
            winsorize_series(scored[factor], lower=0.01, upper=0.99)
        )
        scored["factor_score"] += scored[column] * weight
    return scored.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
