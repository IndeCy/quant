"""四只科技ETF周频反转研究测试。"""

from __future__ import annotations

from examples import a_share_tech_etf_weekly_reversal_study as study


def _metric(
    annualized_return: float = 0.12,
    max_drawdown: float = -0.30,
    sharpe: float = 0.70,
    calmar: float = 0.40,
    annual_turnover: float = 20.0,
):
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
        for key in [*study.FOLD_KEYS, "locked_test", "full"]
    }
    metrics = {
        study.EXPERIMENT_ID: candidate,
        study.STRESS_ID: {"full": _metric(0.09, -0.32, 0.55)},
        study.EQUAL_CONTROL_ID: {"full": _metric(0.10, -0.40, 0.60)},
        study.MOMENTUM_CONTROL_ID: {"full": _metric(0.09, -0.42, 0.50)},
        study.BENCHMARK_CONTROL_ID: {"full": _metric(0.04, -0.45, 0.30)},
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2020, 2027)
    }
    diagnostics = {
        "worst_day": -0.08,
        "expected_shortfall_95": -0.03,
        "quality_correlation": 0.50,
        "selection_share": {symbol: 0.25 for symbol in study.SYMBOLS},
    }
    audit = {"passed": True}
    return metrics, annual, diagnostics, audit


def test_definition_is_frozen_without_grid() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["signal"]["formula"] == "close_t/close_t_minus_5-1"
    assert definition["portfolio"]["bottom_n"] == 2
    assert definition["portfolio"]["parameter_grid"] is False
    assert definition["parameters_fixed_before_backtest"] is True


def test_gate_passes_complete_synthetic_case() -> None:
    metrics, annual, diagnostics, audit = _passing_inputs()

    gate = study.evaluate_gate(metrics, annual, diagnostics, audit)

    assert gate["passed"] is True


def test_gate_rejects_if_candidate_does_not_beat_momentum_mirror() -> None:
    metrics, annual, diagnostics, audit = _passing_inputs()
    metrics[study.MOMENTUM_CONTROL_ID]["full"]["annualized_return"] = 0.11

    gate = study.evaluate_gate(metrics, annual, diagnostics, audit)

    assert gate["passed"] is False
    assert (
        gate["checks"]["return_lift_vs_momentum_at_least_2pct"]
        is False
    )
