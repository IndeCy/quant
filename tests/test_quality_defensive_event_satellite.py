from __future__ import annotations

from examples import quality_defensive_event_satellite_study as study


def test_build_equity_targets_freezes_six_to_one_equity_budget() -> None:
    targets, diagnostics = study.build_equity_targets(
        ["20260131", "20260228"],
        {
            "20260131": {"A": 0.5, "B": 0.5},
            "20260228": {"A": 0.5, "C": 0.5},
        },
        {"20260131": {"B": 0.5, "D": 0.5}},
    )

    quality_share = study.QUALITY_WEIGHT / study.EQUITY_WEIGHT
    event_share = study.EVENT_WEIGHT / study.EQUITY_WEIGHT
    assert targets["20260131"] == {
        "A": 0.5 * quality_share,
        "B": 0.5 * quality_share + 0.5 * event_share,
        "D": 0.5 * event_share,
    }
    assert targets["20260228"]["D"] == 0.5 * event_share
    assert abs(sum(targets["20260228"].values()) - 1.0) < 1e-12
    assert diagnostics["event_active_share"] == 1.0


def test_gate_requires_every_preregistered_check() -> None:
    period = {
        "annualized_return": 0.12,
        "max_drawdown": -0.18,
        "sharpe": 0.82,
        "calmar": 0.66,
        "annual_turnover": 5.0,
    }
    candidate = {
        "full": dict(period),
        "locked_test": dict(period),
        "2015_2017": dict(period),
        "2018_2020": dict(period),
        "2021_2023": dict(period),
        "2024_latest": dict(period),
    }
    baseline = {"locked_test": {**period, "annualized_return": 0.11, "sharpe": 0.80}}
    annual = {
        str(year): {**period, "annualized_return": 0.01}
        for year in range(2015, 2026)
    }

    passed = study.evaluate_gate(
        candidate=candidate,
        baseline=baseline,
        annual=annual,
        stress={"annualized_return": 0.10, "sharpe": 0.65},
        residual={"gate_passed": True},
    )
    assert passed["passed"] is True

    failed = study.evaluate_gate(
        candidate=candidate,
        baseline=baseline,
        annual=annual,
        stress={"annualized_return": 0.089, "sharpe": 0.65},
        residual={"gate_passed": True},
    )
    assert failed["passed"] is False
    assert failed["checks"]["stress_20bps_annual_return_at_least_9pct"] is False
