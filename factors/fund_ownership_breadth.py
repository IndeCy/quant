"""公募基金产品持仓广度变化因子。"""

from __future__ import annotations

import pandas as pd


def score_fund_ownership_breadth_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """持有产品占比增长越快，横截面分数越高。"""
    required = ["symbol", "breadth_change"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"fund ownership breadth frame missing columns: {missing}")
    data = frame.copy()
    data["breadth_change"] = pd.to_numeric(
        data["breadth_change"],
        errors="coerce",
    )
    data = data[data["breadth_change"].gt(0)].copy()
    if data.empty:
        return data.assign(factor_score=pd.Series(dtype=float))
    data["factor_score"] = data["breadth_change"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data
