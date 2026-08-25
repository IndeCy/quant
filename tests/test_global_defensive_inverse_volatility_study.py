"""全球防守三资产逆波动研究测试。"""

from __future__ import annotations

import pandas as pd

from examples import global_defensive_inverse_volatility_study as study


def _metric(
    annualized_return: float = 0.10,
    max_drawdown: float = -0.10,
    sharpe: float = 1.20,
    calmar: float = 1.0,
    annual_turnover: float = 0.5,
) -> dict[str, float]:
    return {
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "calmar": calmar,
        "annual_turnover": annual_turnover,
        "excess_return": 0.1,
    }


def _passing_inputs():
    candidate = {
        key: _metric()
        for key in [*study.FOLDS, "full"]
    }
    all_metrics = {
        study.EXPERIMENT_ID: candidate,
        study.STRESS_ID: {"full": _metric(0.09, -0.11, 1.10)},
        study.EQUAL_CONTROL_ID: {"full": _metric(0.105, -0.11, 1.22)},
        study.SP500_CONTROL_ID: {"full": _metric(0.15, -0.25, 0.90)},
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2015, 2027)
    }
    weights = {
        symbol: {
            "average_weight": 1.0 / 3.0,
            "latest_weight": 1.0 / 3.0,
            "maximum_weight": 0.5,
        }
        for symbol in study.ASSETS
    }
    return all_metrics, annual, weights


def test_definition_freezes_window_and_disables_parameter_grid() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["portfolio"]["lookback_trading_days"] == 60
    assert definition["portfolio"]["leverage"] == 1.0
    assert definition["portfolio"]["weight_cap"] is None
    assert definition["parameter_grid"] is False
    assert definition["parameters_fixed_before_backtest"] is True


def test_gate_passes_only_when_relative_and_stress_checks_pass() -> None:
    all_metrics, annual, weights = _passing_inputs()

    gate = study.evaluate_gate(all_metrics, annual, 0.20, weights)

    assert gate["passed"] is True


def test_gate_rejects_if_equal_weight_opportunity_cost_is_too_large() -> None:
    all_metrics, annual, weights = _passing_inputs()
    all_metrics[study.EQUAL_CONTROL_ID]["full"]["annualized_return"] = 0.12

    gate = study.evaluate_gate(all_metrics, annual, 0.20, weights)

    assert gate["passed"] is False
    assert (
        gate["checks"]["return_shortfall_vs_equal_within_15pct"]
        is False
    )


def test_summarize_weights_preserves_latest_signal() -> None:
    frame = pd.DataFrame(
        [
            {
                "signal_date": date,
                "symbol": symbol,
                "target_weight": weight,
            }
            for date, values in [
                ("20260130", [0.4, 0.3, 0.3]),
                ("20260227", [0.2, 0.5, 0.3]),
            ]
            for symbol, weight in zip(study.ASSETS, values, strict=True)
        ]
    )

    summary = study.summarize_weights(frame)

    assert summary[study.ASSETS[0]]["latest_weight"] == 0.2
    assert summary[study.ASSETS[1]]["latest_weight"] == 0.5
