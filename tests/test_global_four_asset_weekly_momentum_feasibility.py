"""全球四资产周频动量门禁与信号测试。"""

from __future__ import annotations

import pandas as pd

from examples import global_four_asset_weekly_momentum_feasibility_study as study
from factors.etf_weekly_relative_momentum import (
    build_top_momentum_targets,
    calculate_weekly_relative_momentum,
)


def test_signal_uses_no_future_prices() -> None:
    index = pd.date_range("2025-01-01", periods=80, freq="B")
    close = pd.DataFrame(
        {
            "A": range(100, 180),
            "B": range(200, 280),
            "C": range(300, 380),
            "D": range(400, 480),
        },
        index=index,
        dtype=float,
    )
    signal = index[40]
    before = calculate_weekly_relative_momentum(
        close,
        [signal],
        list(close),
    )
    close.loc[index[41]:, "A"] *= 5
    after = calculate_weekly_relative_momentum(
        close,
        [signal],
        list(close),
    )

    pd.testing.assert_frame_equal(before, after)


def test_top_momentum_targets_select_strongest_two() -> None:
    states = pd.DataFrame(
        [
            {
                "signal_date": "20250110",
                "symbol": symbol,
                "momentum": value,
                "rank": rank,
            }
            for rank, (symbol, value) in enumerate(
                [("A", 0.3), ("B", 0.2), ("C", 0.1), ("D", -0.1)],
                start=1,
            )
        ]
    )

    targets, _ = build_top_momentum_targets(states, top_n=2)

    assert targets["20250110"] == {"A": 0.5, "B": 0.5}


def test_feasibility_definition_forbids_holding_return() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["signal_preview"]["future_holding_return_loaded"] is False
    assert definition["signal_preview"]["top_n"] == 2
    assert definition["decision"] == "feasibility_only_no_return_backtest"
