"""Style Rotation Diagnostic研究入口测试。"""

import pandas as pd

from examples.style_rotation_diagnostic_study import (
    build_value_selections,
    classify_market_dependence,
)


def test_build_value_selections_uses_lowest_positive_pb() -> None:
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 4,
            "symbol": ["A", "B", "C", "D"],
            "raw_close": [10.0, 20.0, 5.0, 8.0],
            "bps": [5.0, 5.0, -1.0, 2.0],
        }
    )

    selections, holdings = build_value_selections(candidates, top_n=2)

    assert selections["20240131"] == ["A", "B"]
    assert holdings["pb"].tolist() == [2.0, 4.0]


def test_market_dependence_keeps_positive_alpha_distinction() -> None:
    dependence = {
        "上涨月平均收益": 0.04,
        "下跌月平均收益": -0.02,
        "月度Beta": 0.87,
        "年化Alpha": 0.11,
    }

    assert classify_market_dependence(dependence) == "明显依赖普涨，但不是单纯普涨"
