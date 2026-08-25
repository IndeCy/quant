from __future__ import annotations

import pandas as pd

from examples import limit_up_first_board_open_executable_study as study


def test_definition_freezes_point_in_time_execution_before_returns() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["execution"]["limit_state"] == "point_in_time_at_open"
    assert definition["parameters_fixed_before_corrected_return_loading"] is True
    assert definition["promotion_scope"] == "research_only_never_auto_register"


def test_open_limit_flags_do_not_use_later_intraday_touch() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-05"), "000001.SZ"),
            (pd.Timestamp("2026-01-05"), "000002.SZ"),
        ],
        names=["date", "symbol"],
    )
    bars = pd.DataFrame(
        {
            "open": [10.5, 11.0],
            "high": [11.0, 11.0],
            "low": [10.4, 10.8],
            "limit_up": [True, True],
            "limit_down": [False, False],
        },
        index=index,
    )

    result = study.apply_open_point_in_time_limits(bars)

    assert result["limit_up"].tolist() == [False, True]


def test_open_limit_down_requires_open_equal_low() -> None:
    bars = pd.DataFrame(
        {
            "open": [9.5, 9.0],
            "high": [9.6, 9.2],
            "low": [9.0, 9.0],
            "limit_up": [False, False],
            "limit_down": [True, True],
        }
    )

    result = study.apply_open_point_in_time_limits(bars)

    assert result["limit_down"].tolist() == [False, True]
