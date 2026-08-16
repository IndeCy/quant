from __future__ import annotations

import pandas as pd

from examples import global_defensive_equal_robustness_study as study


def test_delay_targets_moves_signal_one_trading_day() -> None:
    calendar = list(pd.to_datetime(["2026-01-29", "2026-01-30", "2026-02-02"]))
    delayed = study.delay_targets_one_day(
        {"20260130": {"ETF": 1.0}},
        calendar,
    )
    assert delayed == {"20260202": {"ETF": 1.0}}


def test_robustness_matrix_is_fixed_before_run() -> None:
    assert set(study.SCENARIO_WEIGHTS) == {
        "baseline_monthly_5bps",
        "sp500_40_gold30_bond30",
        "sp500_30_gold40_bond30",
        "sp500_30_gold30_bond40",
    }
    assert all(
        abs(sum(weights.values()) - 1.0) < 1e-12
        for weights in study.SCENARIO_WEIGHTS.values()
    )
