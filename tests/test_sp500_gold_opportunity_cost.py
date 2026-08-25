"""标普500与黄金固定60/40机会成本研究测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from examples import sp500_gold_opportunity_cost_study as study


def _metric(
    *,
    annual_return: float = 0.13,
    drawdown: float = -0.15,
    sharpe: float = 1.10,
) -> dict[str, float]:
    return {
        "annualized_return": annual_return,
        "max_drawdown": drawdown,
        "sharpe": sharpe,
        "calmar": annual_return / abs(drawdown),
        "excess_return": 0.20,
        "annual_turnover": 0.30,
    }


def _passing_metrics() -> dict[str, dict[str, dict[str, float]]]:
    candidate = {
        period: _metric()
        for period in study.PERIODS
    }
    risk = {
        period: _metric(
            annual_return=0.115,
            drawdown=-0.15,
            sharpe=0.95,
        )
        for period in study.PERIODS
    }
    direct = {
        period: _metric(
            annual_return=0.15,
            drawdown=-0.25,
            sharpe=0.90,
        )
        for period in study.PERIODS
    }
    stress = {
        period: _metric(annual_return=0.125, sharpe=1.00)
        for period in study.PERIODS
    }
    return {
        study.EXPERIMENT_ID: candidate,
        study.NOMINAL_CONTROL_ID: risk,
        study.RISK_CONTROL_ID: risk,
        study.DIRECT_ID: direct,
        study.STRESS_ID: stress,
    }


def test_definition_freezes_simple_60_40_without_grid() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["candidate"]["assets"] == {
        study.SP500: 0.60,
        study.GOLD: 0.40,
    }
    assert definition["candidate"]["weight_grid"] is False
    assert definition["parameters_fixed_before_backtest"] is True
    assert (
        definition["promotion_scope"]
        == "research_only_never_auto_register"
    )


def test_closed_form_calibration_matches_candidate_volatility() -> None:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2014-01-15", "2018-12-31")
    frame = pd.DataFrame(
        {
            study.SP500: 100 * np.exp(np.cumsum(rng.normal(0, 0.012, len(dates)))),
            study.GOLD: 100 * np.exp(np.cumsum(rng.normal(0, 0.010, len(dates)))),
            study.BOND: 100 * np.exp(np.cumsum(rng.normal(0, 0.002, len(dates)))),
        },
        index=dates,
    )

    result = study.calibrate_risk_control(frame)

    assert 0.0 <= result["risk_control_sp500_weight"] <= 1.0
    assert abs(
        result["candidate_volatility"]
        - result["risk_control_volatility"]
    ) < 1e-10
    assert result["calibration_observations"] >= 1000


def test_gate_requires_opportunity_cost_outperformance() -> None:
    metrics = _passing_metrics()
    annual = {
        strategy_id: {
            str(year): _metric()
            for year in range(2019, 2027)
        }
        for strategy_id in metrics
    }
    diagnostics = {
        "candidate_volatility": 0.12,
        "direct_sp500_volatility": 0.18,
        "risk_control_volatility": 0.125,
        "worst_day": -0.05,
        "expected_shortfall_95": -0.02,
        "quality_correlation": 0.20,
    }

    passed = study.evaluate_gate(metrics, annual, diagnostics)
    assert passed["passed"] is True

    metrics[study.RISK_CONTROL_ID]["oos_full"]["annualized_return"] = 0.125
    failed = study.evaluate_gate(metrics, annual, diagnostics)

    assert failed["passed"] is False
    assert (
        failed["checks"]["return_lift_vs_risk_control_at_least_1pct"]
        is False
    )


def test_gate_rejects_low_return_without_direct_risk_reduction() -> None:
    metrics = _passing_metrics()
    annual = {
        strategy_id: {
            str(year): _metric()
            for year in range(2019, 2027)
        }
        for strategy_id in metrics
    }
    diagnostics = {
        "candidate_volatility": 0.17,
        "direct_sp500_volatility": 0.18,
        "risk_control_volatility": 0.17,
        "worst_day": -0.05,
        "expected_shortfall_95": -0.02,
        "quality_correlation": 0.20,
    }

    gate = study.evaluate_gate(metrics, annual, diagnostics)

    assert gate["passed"] is False
    assert (
        gate["checks"]["volatility_reduction_vs_direct_at_least_15pct"]
        is False
    )


def test_decision_reason_lists_actual_failed_gate() -> None:
    gate = {
        "passed": False,
        "checks": {
            "return_lift_vs_risk_control_at_least_1pct": False,
            "history_audit": True,
        },
    }

    reason = study.build_decision_reason(gate)

    assert "return_lift_vs_risk_control_at_least_1pct" in reason
    assert "归档且不注册" in reason
