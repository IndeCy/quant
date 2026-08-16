from __future__ import annotations

from examples import quality_global_defensive_barbell_study as study


def test_barbell_definition_is_fixed_half_domestic_half_global() -> None:
    definition = study.RESEARCH_SPEC.definition
    assert definition["quality_block"]["weight"] == 0.50
    assert sum(study.FUND_WEIGHTS.values()) == 0.50
    assert definition["portfolio"]["allocation_grid"] is False
    assert definition["risk_overlay"]["scope"] == "quality_block_only"


def test_barbell_gate_requires_all_checks() -> None:
    metric = {
        "annualized_return": 0.12,
        "max_drawdown": -0.12,
        "sharpe": 1.0,
        "calmar": 1.0,
        "annual_turnover": 3.0,
    }
    periods = {
        "full": dict(metric),
        "locked_test": dict(metric),
        "2015_2017": dict(metric),
        "2018_2020": dict(metric),
        "2021_2023": dict(metric),
        "2024_latest": dict(metric),
    }
    metrics = {
        study.EXPERIMENT_ID: periods,
        study.QUALITY_DEFENSIVE_ID: {
            "full": {**metric, "annualized_return": 0.12, "max_drawdown": -0.15, "sharpe": 0.9}
        },
        study.GLOBAL_ID: {
            "full": {**metric, "annualized_return": 0.10}
        },
    }
    annual = {
        str(year): {**metric, "annualized_return": 0.01}
        for year in range(2015, 2026)
    }
    gate = study.evaluate_gate(
        metrics,
        annual,
        {"annualized_return": 0.10, "sharpe": 0.9},
        {"candidate_quality": 0.7, "candidate_global": 0.8},
    )
    assert gate["passed"] is True
