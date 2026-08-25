"""A股科技ETF周频轮动测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from examples import a_share_tech_etf_rotation_study as study
from factors.etf_relative_strength import (
    calculate_relative_strength_states,
    weekly_signal_dates,
)
from portfolio.tech_etf_rotation import build_tech_rotation_targets
from runtime.paths import RuntimePaths


def test_definition_freezes_universe_frequency_and_slots() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert set(definition["universe"]["symbols"]) == set(study.TECH_SYMBOLS)
    assert definition["portfolio"]["top_n"] == 2
    assert definition["portfolio"]["slot_weight"] == 0.40
    assert definition["portfolio"]["defensive_base_weight"] == 0.20
    assert definition["portfolio"]["rebalance"] == "weekly"
    assert definition["portfolio"]["parameter_grid"] is False


def test_weekly_signals_use_actual_last_trading_day() -> None:
    calendar = list(pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-09", "2026-01-12", "2026-01-15"]))

    signals = weekly_signal_dates(calendar)

    assert signals == [pd.Timestamp("2026-01-09"), pd.Timestamp("2026-01-15")]


def test_relative_strength_uses_only_past_prices_and_ranks() -> None:
    dates = pd.date_range("2026-01-01", periods=7, freq="B")
    close = pd.DataFrame(
        {
            "A": [1, 1, 1, 1, 1, 1.1, 1.2],
            "B": [1, 1, 1, 1, 1, 1.05, 1.1],
        },
        index=dates,
    )

    states = calculate_relative_strength_states(
        close,
        [dates[-1]],
        ["A", "B"],
        momentum_window=2,
        trend_window=4,
    )

    assert states.sort_values("rank").iloc[0]["symbol"] == "A"
    assert states["trend_active"].all()


def test_unused_slots_flow_to_bond() -> None:
    states = pd.DataFrame(
        {
            "signal_date": ["20260109", "20260109", "20260109"],
            "symbol": ["A", "B", "C"],
            "rank": [1, 2, 3],
            "trend_active": [True, False, False],
        }
    )

    targets, holdings = build_tech_rotation_targets(
        states,
        defensive_symbol="BOND",
    )

    assert targets["20260109"] == {"A": 0.40, "BOND": 0.60}
    assert holdings["target_weight"].sum() == 1.0


def test_same_fingerprint_skips_heavy_calculation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        paths.monitoring_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    attempt = study.begin_research_attempt(
        study.RESEARCH_SPEC,
        paths=paths,
        data_as_of="20260728",
        data_version=study._data_version(paths),
    )
    study.complete_research_attempt(
        attempt,
        metrics={"gate": {"passed": False}},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中研究指纹后不得重新计算")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)

    result = study.run_study(paths, "20260728")

    assert result["reused"] is True
