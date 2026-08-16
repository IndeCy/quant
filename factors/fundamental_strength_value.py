"""基本面强度与点时价值因子的横截面打分。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.quality import winsorize_series, zscore_series


STRENGTH_COLUMNS = (
    "roa",
    "ocf_to_or",
    "ocf_to_profit",
    "netprofit_yoy",
    "debt_to_assets",
    "grossprofit_margin",
    "assets_turn",
)
VALUE_COLUMNS = ("earnings_yield", "book_yield")


def score_fundamental_strength_value_frame(
    frame: pd.DataFrame,
    *,
    value_weight: float = 0.30,
) -> pd.DataFrame:
    """把七项财务健康度与点时价值合成连续分数。

    财务健康度采用离散信号，降低极端财务值对排序的支配；价值部分仍使用
    横截面缩尾和标准化，以便与强度分数处于可比较尺度。
    """
    if not 0.0 <= value_weight <= 1.0:
        raise ValueError("value_weight must be between 0 and 1")
    required = ["symbol", *STRENGTH_COLUMNS, *VALUE_COLUMNS]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"fundamental strength value frame missing columns: {missing}")

    data = frame.copy()
    numeric = [*STRENGTH_COLUMNS, *VALUE_COLUMNS]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(data[numeric]).all(axis=1)
    data = data[finite].copy()
    if data.empty:
        return data.assign(
            fundamental_strength=pd.Series(dtype=float),
            value_score=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )

    # 四项绝对门槛刻画盈利与现金为正，三项截面门槛刻画相对经营质量。
    data["flag_positive_roa"] = data["roa"].gt(0).astype(float)
    data["flag_positive_ocf"] = data["ocf_to_or"].gt(0).astype(float)
    data["flag_cash_backed_profit"] = data["ocf_to_profit"].gt(1).astype(float)
    data["flag_positive_profit_growth"] = data["netprofit_yoy"].gt(0).astype(float)
    data["flag_low_leverage"] = data["debt_to_assets"].le(data["debt_to_assets"].median()).astype(float)
    data["flag_high_margin"] = data["grossprofit_margin"].ge(data["grossprofit_margin"].median()).astype(float)
    data["flag_high_asset_turnover"] = data["assets_turn"].ge(data["assets_turn"].median()).astype(float)
    flag_columns = [column for column in data.columns if column.startswith("flag_")]
    data["fundamental_strength"] = data[flag_columns].mean(axis=1)
    data["fundamental_strength_z"] = zscore_series(data["fundamental_strength"])

    value_parts: list[pd.Series] = []
    for column in VALUE_COLUMNS:
        value_parts.append(
            zscore_series(winsorize_series(data[column], lower=0.01, upper=0.99))
        )
    data["value_score"] = pd.concat(value_parts, axis=1).mean(axis=1)
    data["factor_score"] = (
        (1.0 - value_weight) * data["fundamental_strength_z"]
        + value_weight * data["value_score"]
    )
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
