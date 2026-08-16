from __future__ import annotations

import pandas as pd

from examples import nasdaq_gold_sp500_hurdle_robustness_study as study


def _metrics(
    *,
    candidate_return: float = 0.20,
    candidate_drawdown: float = -0.20,
    candidate_sharpe: float = 1.20,
) -> dict[str, dict[str, dict[str, float]]]:
    result: dict[str, dict[str, dict[str, float]]] = {}
    for scenario_id in study.SCENARIO_IDS:
        result[scenario_id] = {
            "oos_full": {
                "annualized_return": candidate_return,
                "max_drawdown": candidate_drawdown,
                "sharpe": candidate_sharpe,
            },
            **{
                fold: {
                    "annualized_return": 0.10,
                    "max_drawdown": -0.20,
                    "sharpe": 1.0,
                }
                for fold in study.base.FOLD_KEYS
            },
        }
    result[study.SP500_ID] = {
        "oos_full": {
            "annualized_return": 0.18,
            "max_drawdown": -0.30,
            "sharpe": 0.95,
        }
    }
    return result


def test_delay_targets_one_day_creates_t2_input() -> None:
    calendar = list(pd.to_datetime(["2026-01-29", "2026-01-30", "2026-02-02"]))
    delayed = study.delay_targets_one_day(
        {"20260130": {"159941.SZ": 0.6, "518880.SH": 0.4}},
        calendar,
    )
    assert delayed == {
        "20260202": {"159941.SZ": 0.6, "518880.SH": 0.4}
    }


def test_gate_passes_only_when_every_scenario_dominates_sp500() -> None:
    metrics = _metrics()
    volatilities = {
        **{scenario_id: 0.17 for scenario_id in study.SCENARIO_IDS},
        study.SP500_ID: 0.19,
    }
    gate = study.evaluate_gate(metrics, volatilities, True)
    assert gate["passed"] is True
    assert all(gate["checks"].values())


def test_gate_fails_on_one_pressure_scenario_without_selection() -> None:
    metrics = _metrics()
    metrics[study.COST_ID]["oos_full"]["annualized_return"] = 0.181
    volatilities = {
        **{scenario_id: 0.17 for scenario_id in study.SCENARIO_IDS},
        study.SP500_ID: 0.19,
    }
    gate = study.evaluate_gate(metrics, volatilities, True)
    assert gate["passed"] is False
    assert (
        gate["checks"][
            "all_scenarios_return_lift_vs_sp500_at_least_05pct"
        ]
        is False
    )


def test_spec_freezes_all_promised_pressure_dimensions() -> None:
    definition = study.RESEARCH_SPEC.definition
    assert definition["source_experiment"] == study.base.EXPERIMENT_ID
    assert study.LOW_NASDAQ_ID in definition["scenarios"][
        "weight_neighborhoods"
    ]
    assert study.HIGH_NASDAQ_ID in definition["scenarios"][
        "weight_neighborhoods"
    ]
    assert study.QUARTERLY_ID in definition["scenarios"]
    assert study.COST_ID in definition["scenarios"]
    assert study.T2_ID in definition["scenarios"]
    assert definition["promotion_scope"] == "research_only_never_auto_register"
