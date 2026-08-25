"""Piotroski F-Score 与价值池组合因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_piotroski_value_frame(
    frame: pd.DataFrame,
    *,
    high_score_threshold: int = 8,
    value_quantile: float = 0.20,
) -> pd.DataFrame:
    """在高账面市值比股票中选择财务改善得分较高的公司。

    F-Score 是主排序，账面市值比只负责定义价值池并打破同分。函数只输出
    连续信号分数，不决定最终持仓数量和权重。
    """
    required = ["symbol", "f_score", "book_to_market"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"piotroski frame missing columns: {missing}")
    if high_score_threshold < 0 or high_score_threshold > 9:
        raise ValueError("high_score_threshold must be between 0 and 9")
    if value_quantile <= 0 or value_quantile >= 1:
        raise ValueError("value_quantile must be between 0 and 1")

    data = frame.copy()
    data["f_score"] = pd.to_numeric(data["f_score"], errors="coerce")
    data["book_to_market"] = pd.to_numeric(
        data["book_to_market"],
        errors="coerce",
    )
    valid = (
        np.isfinite(data[["f_score", "book_to_market"]]).all(axis=1)
        & data["book_to_market"].gt(0)
    )
    data = data[valid].copy()
    if data.empty:
        return data.assign(
            book_to_market_percentile=pd.Series(dtype=float),
            factor_score=pd.Series(dtype=float),
        )

    data["book_to_market_percentile"] = data["book_to_market"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    data = data[
        data["book_to_market_percentile"].ge(1.0 - value_quantile)
        & data["f_score"].ge(high_score_threshold)
    ].copy()
    # 小于 0.01 的价值分位尾数只用于同分排序，不会让 8 分越过 9 分。
    data["factor_score"] = (
        data["f_score"] + data["book_to_market_percentile"] * 0.01
    )
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
