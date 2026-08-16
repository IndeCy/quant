"""跳过近月动量与低波动的防御型横截面打分。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.quality import winsorize_series, zscore_series


def score_defensive_momentum_frame(
    frame: pd.DataFrame,
    *,
    momentum_weight: float = 0.50,
) -> pd.DataFrame:
    """计算120日至20日前动量，并与60日低波动组合。"""
    if not 0.0 <= momentum_weight <= 1.0:
        raise ValueError("momentum_weight must be between 0 and 1")
    required = ["symbol", "ret20", "ret120", "vol60"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"defensive momentum frame missing columns: {missing}")

    data = frame.copy()
    data[["ret20", "ret120", "vol60"]] = data[
        ["ret20", "ret120", "vol60"]
    ].apply(pd.to_numeric, errors="coerce")
    valid = (
        np.isfinite(data[["ret20", "ret120", "vol60"]]).all(axis=1)
        & data["ret20"].gt(-1)
        & data["ret120"].gt(-1)
        & data["vol60"].gt(0)
    )
    data = data[valid].copy()
    data["momentum_skip_20d"] = (
        (1.0 + data["ret120"]) / (1.0 + data["ret20"]) - 1.0
    )
    data = data[data["momentum_skip_20d"].gt(0)].copy()
    if data.empty:
        return data.assign(
            momentum_score=pd.Series(dtype=float),
            low_volatility_score=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )

    data["momentum_score"] = zscore_series(
        winsorize_series(data["momentum_skip_20d"], lower=0.01, upper=0.99)
    )
    data["low_volatility_score"] = zscore_series(
        winsorize_series(-data["vol60"], lower=0.01, upper=0.99)
    )
    data["factor_score"] = (
        momentum_weight * data["momentum_score"]
        + (1.0 - momentum_weight) * data["low_volatility_score"]
    )
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
