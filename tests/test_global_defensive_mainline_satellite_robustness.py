from __future__ import annotations

import pandas as pd

from examples import global_defensive_mainline_satellite_robustness_study as study


def test_definition_freezes_neighborhood_without_selection() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["selection_from_scenarios"] is False
    assert definition["parameters_fixed_before_loading_daily_returns"] is True
    assert set(study.SCENARIOS) == {
        "satellite_10pct_10bps",
        "baseline_20pct_10bps",
        "satellite_30pct_10bps",
        "baseline_20pct_100bps",
    }


def test_rolling_diagnostics_measure_positive_and_core_lift() -> None:
    dates = pd.bdate_range("2020-01-01", periods=300)
    daily = pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "portfolio_nav": 1.001 ** pd.Series(range(300)),
            "core_nav": 1.0005 ** pd.Series(range(300)),
        }
    )

    result = study.rolling_return_diagnostics(daily)

    assert result["positive_share"] == 1.0
    assert result["beat_core_share"] == 1.0


def test_block_bootstrap_is_deterministic() -> None:
    daily = pd.DataFrame(
        {
            "portfolio_nav": [1.0 * 1.001**i for i in range(80)],
            "core_nav": [1.0 * 1.0005**i for i in range(80)],
        }
    )

    left = study.block_bootstrap_return_lift(
        daily,
        samples=20,
        block_days=5,
        seed=7,
    )
    right = study.block_bootstrap_return_lift(
        daily,
        samples=20,
        block_days=5,
        seed=7,
    )

    pd.testing.assert_frame_equal(left, right)
