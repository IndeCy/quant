"""境内纳指黄金相对标普500硬门槛测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from examples import nasdaq_gold_sp500_hurdle_study as study


def _metric(
    annual_return: float = 0.20,
    drawdown: float = -0.20,
    sharpe: float = 1.20,
) -> dict[str, float]:
    return {
        "annualized_return": annual_return,
        "max_drawdown": drawdown,
        "sharpe": sharpe,
        "calmar": annual_return / abs(drawdown),
        "excess_return": 0.20,
        "annual_turnover": 0.40,
    }


def _passing_metrics() -> dict[str, dict[str, dict[str, float]]]:
    candidate = {period: _metric() for period in study.PERIODS}
    risk = {
        period: _metric(0.17, -0.20, 1.00)
        for period in study.PERIODS
    }
    sp500 = {
        period: _metric(0.18, -0.24, 1.00)
        for period in study.PERIODS
    }
    nasdaq = {
        period: _metric(0.23, -0.32, 0.95)
        for period in study.PERIODS
    }
    stress = {
        period: _metric(0.195, -0.20, 1.15)
        for period in study.PERIODS
    }
    return {
        study.EXPERIMENT_ID: candidate,
        study.RISK_CONTROL_ID: risk,
        study.SP500_DIRECT_ID: sp500,
        study.NASDAQ_DIRECT_ID: nasdaq,
        study.STRESS_ID: stress,
    }


def test_definition_freezes_domestic_etfs_and_hard_sp500_hurdle() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["candidate"]["assets"] == {
        study.NASDAQ: 0.60,
        study.GOLD: 0.40,
    }
    assert definition["candidate"]["weight_grid"] is False
    assert definition["hard_opportunity_cost"] == {study.SP500: 1.0}
    assert definition["parameters_fixed_before_backtest"] is True
    assert (
        definition["promotion_scope"]
        == "research_only_never_auto_register"
    )


def test_risk_calibration_matches_candidate_volatility() -> None:
    rng = np.random.default_rng(31)
    dates = pd.bdate_range("2015-07-13", "2018-12-31")
    frame = pd.DataFrame(
        {
            study.NASDAQ: 100
            * np.exp(np.cumsum(rng.normal(0, 0.014, len(dates)))),
            study.GOLD: 100
            * np.exp(np.cumsum(rng.normal(0, 0.010, len(dates)))),
            study.SP500: 100
            * np.exp(np.cumsum(rng.normal(0, 0.012, len(dates)))),
            study.BOND: 100
            * np.exp(np.cumsum(rng.normal(0, 0.002, len(dates)))),
        },
        index=dates,
    )

    calibration = study.calibrate_risk_control(frame)

    assert calibration["calibration_observations"] >= 750
    assert 0 <= calibration["risk_control_sp500_weight"] <= 1
    assert abs(
        calibration["candidate_volatility"]
        - calibration["risk_control_volatility"]
    ) < 1e-10


def test_gate_requires_material_direct_sp500_outperformance() -> None:
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
        "risk_control_volatility": 0.17,
        "direct_sp500_volatility": 0.18,
        "direct_nasdaq_volatility": 0.24,
        "worst_day": -0.06,
        "expected_shortfall_95": -0.025,
        "quality_correlation": 0.20,
    }

    passed = study.evaluate_gate(
        metrics,
        annual,
        diagnostics,
        {"passed": True},
    )
    assert passed["passed"] is True

    metrics[study.SP500_DIRECT_ID]["oos_full"]["annualized_return"] = 0.195
    failed = study.evaluate_gate(
        metrics,
        annual,
        diagnostics,
        {"passed": True},
    )

    assert failed["passed"] is False
    assert (
        failed["checks"]["return_lift_vs_direct_sp500_at_least_1pct"]
        is False
    )


def test_decision_reason_lists_failed_hurdle() -> None:
    gate = {
        "passed": False,
        "checks": {
            "return_lift_vs_direct_sp500_at_least_1pct": False,
            "data_audit": True,
        },
    }

    reason = study.build_decision_reason(gate)

    assert "return_lift_vs_direct_sp500_at_least_1pct" in reason
    assert "归档且不注册" in reason
