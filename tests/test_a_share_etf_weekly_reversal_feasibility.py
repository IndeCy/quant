"""A股ETF短期反转数据门禁和信号测试。"""

from __future__ import annotations

import pandas as pd

from examples import a_share_etf_weekly_reversal_feasibility_study as feasibility
from factors.etf_short_term_reversal import (
    build_ranked_targets,
    calculate_weekly_reversal_states,
)


def test_signal_uses_only_signal_day_and_prior_prices() -> None:
    index = pd.date_range("2025-01-01", periods=30, freq="B")
    close = pd.DataFrame(
        {
            "A": range(100, 130),
            "B": range(200, 230),
            "C": range(300, 330),
        },
        index=index,
        dtype=float,
    )
    signal = index[15]
    before = calculate_weekly_reversal_states(
        close,
        [signal],
        ["A", "B", "C"],
    )
    close.loc[index[16]:, "A"] *= 4.0
    after = calculate_weekly_reversal_states(
        close,
        [signal],
        ["A", "B", "C"],
    )

    pd.testing.assert_frame_equal(before, after)


def test_reversal_targets_select_lowest_trailing_returns() -> None:
    states = pd.DataFrame(
        [
            {
                "signal_date": "20250110",
                "symbol": symbol,
                "return_5d": value,
                "reversal_rank": rank,
                "momentum_rank": 4 - rank,
            }
            for rank, (symbol, value) in enumerate(
                [("LOW", -0.1), ("MID", 0.0), ("HIGH", 0.1)],
                start=1,
            )
        ]
    )

    targets, holdings = build_ranked_targets(
        states,
        top_n=2,
        rank_column="reversal_rank",
    )

    assert targets["20250110"] == {"LOW": 0.5, "MID": 0.5}
    assert set(holdings["symbol"]) == {"LOW", "MID"}


def test_feasibility_definition_forbids_return_backtest() -> None:
    definition = feasibility.RESEARCH_SPEC.definition

    assert definition["signal_preview"]["future_return_loading"] is False
    assert definition["decision"] == "feasibility_only_no_return_backtest"
    assert len(definition["universe"]) == 12
