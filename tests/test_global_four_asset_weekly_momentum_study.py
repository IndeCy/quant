"""全球四资产周频动量研究测试。"""

from __future__ import annotations

from examples import global_four_asset_weekly_momentum_study as study


def _metric(
    annualized_return: float = 0.16,
    max_drawdown: float = -0.18,
    sharpe: float = 1.20,
    calmar: float = 0.80,
    annual_turnover: float = 6.0,
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
        study.STRESS_ID: {"full": _metric(0.13, -0.20, 0.95)},
        study.EQUAL_CONTROL_ID: {"full": _metric(0.14, -0.20, 1.10)},
        study.GROWTH_CONTROL_ID: {"full": _metric(0.19, -0.22, 1.15)},
        study.SP500_CONTROL_ID: {"full": _metric(0.15, -0.28, 0.95)},
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2016, 2027)
    }
    diagnostics = {
        "worst_day": -0.06,
        "expected_shortfall_95": -0.025,
        "quality_correlation": 0.30,
        "selection_share": {symbol: 0.25 for symbol in study.SYMBOLS},
    }
    return metrics, annual, diagnostics, {"passed": True}


def test_definition_freezes_weekly_20d_top2_without_grid() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["signal"]["formula"] == "close_t/close_t_minus_20-1"
    assert definition["portfolio"]["top_n"] == 2
    assert definition["portfolio"]["parameter_grid"] is False
    assert definition["parameters_fixed_before_backtest"] is True


def test_gate_passes_complete_synthetic_case() -> None:
    metrics, annual, diagnostics, audit = _passing_inputs()

    gate = study.evaluate_gate(metrics, annual, diagnostics, audit)

    assert gate["passed"] is True


def test_gate_rejects_if_strategy_fails_sp500_hurdle() -> None:
    metrics, annual, diagnostics, audit = _passing_inputs()
    metrics[study.SP500_CONTROL_ID]["full"]["annualized_return"] = 0.158

    gate = study.evaluate_gate(metrics, annual, diagnostics, audit)

    assert gate["passed"] is False
    assert (
        gate["checks"]["return_lift_vs_sp500_at_least_05pct"]
        is False
    )
