"""低应计利润质量因子。"""

from __future__ import annotations

import pandas as pd


REQUIRED_COLUMNS = [
    "symbol",
    "net_income",
    "operating_cashflow",
    "average_total_assets",
    "accrual_ratio",
]


def score_low_accrual_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """对正利润公司的应计利润率做缩尾和反向分位排名。"""
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"accrual quality frame missing columns: {missing}")

    data = frame.copy()
    numeric = [
        "net_income",
        "operating_cashflow",
        "average_total_assets",
        "accrual_ratio",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = (
        data[numeric].notna().all(axis=1)
        & data["net_income"].gt(0)
        & data["average_total_assets"].gt(0)
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(
            accrual_ratio_winsorized=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )

    lower, upper = data["accrual_ratio"].quantile([0.01, 0.99])
    data["accrual_ratio_winsorized"] = data["accrual_ratio"].clip(lower, upper)
    # 应计利润越低，利润的现金支撑越强，因此反向排名。
    data["factor_score"] = data["accrual_ratio_winsorized"].rank(
        method="average",
        ascending=False,
        pct=True,
    )
    return data
