"""融资净买入强度因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score_margin_flow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """正融资净买入强度越高，横截面分数越高。

    百分位排名降低极端融资流对连续分数的支配，但不改变原始排序。函数
    只输出信号，不决定 TopN、权重或成交。
    """
    required = ["symbol", "margin_flow_intensity"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"margin flow frame missing columns: {missing}")
    data = frame.copy()
    data["margin_flow_intensity"] = pd.to_numeric(
        data["margin_flow_intensity"],
        errors="coerce",
    )
    valid = (
        np.isfinite(data["margin_flow_intensity"])
        & data["margin_flow_intensity"].gt(0)
    )
    data = data[valid].copy()
    data["factor_score"] = data["margin_flow_intensity"].rank(
        method="average",
        ascending=True,
        pct=True,
    )
    return data.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
