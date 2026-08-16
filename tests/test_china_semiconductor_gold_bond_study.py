"""半导体黄金国债三等权研究测试。"""

from __future__ import annotations

from examples import china_semiconductor_gold_bond_study as study


def _metric(
    annualized_return: float = 0.12,
    max_drawdown: float = -0.16,
    sharpe: float = 1.05,
    calmar: float = 0.75,
    annual_turnover: float = 0.5,
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
        study.STRESS_ID: {"full": _metric(0.10, -0.17, 0.90)},
        study.GOLD_BOND_ID: {"full": _metric(0.09, -0.16, 0.95)},
        study.SEMICONDUCTOR_ID: {"full": _metric(0.15, -0.45, 0.70)},
        study.SP500_ID: {"full": _metric(0.14, -0.30, 0.85)},
        study.GLOBAL_ID: {"full": _metric(0.13, -0.14, 1.12)},
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2020, 2027)
    }
    diagnostics = {
        "worst_day": -0.06,
        "expected_shortfall_95": -0.025,
        "quality_correlation": 0.30,
    }
    return metrics, annual, diagnostics, {"passed": True}


def test_definition_freezes_equal_weights_without_grid() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["assets"]["weights"] == {
        symbol: 1 / 3 for symbol in study.feasibility.SYMBOLS
    }
    assert definition["portfolio"]["weight_grid"] is False
    assert definition["portfolio"]["timing"] is False
    assert definition["parameters_fixed_before_backtest"] is True


def test_gate_passes_complete_synthetic_case() -> None:
    metrics, annual, diagnostics, audit = _passing_inputs()

    gate = study.evaluate_gate(metrics, annual, diagnostics, audit)

    assert gate["passed"] is True


def test_gate_rejects_excessive_sp500_opportunity_cost() -> None:
    metrics, annual, diagnostics, audit = _passing_inputs()
    metrics[study.SP500_ID]["full"]["annualized_return"] = 0.16

    gate = study.evaluate_gate(metrics, annual, diagnostics, audit)

    assert gate["passed"] is False
    assert gate["checks"]["return_shortfall_vs_sp500_within_3pct"] is False
