"""标普黄金共同波动目标机会成本测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from examples import sp500_gold_vol_target_study as study


def _prices() -> pd.DataFrame:
    rng = np.random.default_rng(19)
    dates = pd.bdate_range("2014-01-02", periods=180)
    return pd.DataFrame(
        {
            study.SP500: 100 * np.exp(
                np.cumsum(rng.normal(0, 0.015, len(dates)))
            ),
            study.GOLD: 100 * np.exp(
                np.cumsum(rng.normal(0, 0.010, len(dates)))
            ),
        },
        index=dates,
    )


def _metric(
    annual_return: float = 0.14,
    drawdown: float = -0.15,
    sharpe: float = 1.10,
) -> dict[str, float]:
    return {
        "annualized_return": annual_return,
        "max_drawdown": drawdown,
        "sharpe": sharpe,
        "calmar": annual_return / abs(drawdown),
        "excess_return": 0.20,
        "annual_turnover": 0.70,
    }


def _passing_metrics() -> dict[str, dict[str, dict[str, float]]]:
    candidate = {period: _metric() for period in study.PERIODS}
    control = {
        period: _metric(0.12, -0.15, 0.95)
        for period in study.PERIODS
    }
    direct = {
        period: _metric(0.16, -0.25, 0.90)
        for period in study.PERIODS
    }
    stress = {
        period: _metric(0.135, -0.15, 1.00)
        for period in study.PERIODS
    }
    return {
        study.EXPERIMENT_ID: candidate,
        study.VOL_CONTROL_ID: control,
        study.DIRECT_ID: direct,
        study.STRESS_ID: stress,
    }


def test_definition_uses_same_fixed_risk_mechanism() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["candidate_risk_block"] == {
        "assets": {study.SP500: 0.60, study.GOLD: 0.40},
        "weight_grid": False,
    }
    assert definition["simple_control_risk_block"] == {study.SP500: 1.0}
    assert (
        definition["shared_risk_budget"][
            "same_mechanism_for_candidate_and_control"
        ]
        is True
    )
    assert definition["parameters_fixed_before_backtest"] is True


def test_targets_use_only_history_available_at_signal() -> None:
    prices = _prices()
    signal = prices.index[100]
    targets_before = study.build_vol_target_targets(
        prices,
        [signal],
        study.RISK_BLOCK,
    )
    changed = prices.copy()
    changed.loc[changed.index > signal, study.SP500] *= 10.0
    targets_after = study.build_vol_target_targets(
        changed,
        [signal],
        study.RISK_BLOCK,
    )

    assert targets_before == targets_after


def test_targets_are_fully_invested_without_leverage() -> None:
    prices = _prices()
    signals = [prices.index[100], prices.index[150]]

    targets = study.build_vol_target_targets(
        prices,
        signals,
        study.RISK_BLOCK,
    )

    for weights in targets.values():
        assert abs(sum(weights.values()) - 1.0) < 1e-12
        assert 0.0 <= weights[study.BOND] <= 1.0
        assert weights[study.SP500] <= 0.60
        assert weights[study.GOLD] <= 0.40


def test_gate_requires_same_mechanism_opportunity_cost() -> None:
    metrics = _passing_metrics()
    annual = {
        strategy_id: {
            str(year): _metric()
            for year in range(2019, 2027)
        }
        for strategy_id in metrics
    }
    diagnostics = {
        "candidate_volatility": 0.115,
        "vol_target_control_volatility": 0.12,
        "direct_sp500_volatility": 0.18,
        "candidate_average_risk_allocation": 0.80,
        "worst_day": -0.05,
        "expected_shortfall_95": -0.02,
        "quality_correlation": 0.20,
    }

    passed = study.evaluate_gate(metrics, annual, diagnostics)
    assert passed["passed"] is True

    metrics[study.VOL_CONTROL_ID]["oos_full"]["annualized_return"] = 0.135
    failed = study.evaluate_gate(metrics, annual, diagnostics)

    assert failed["passed"] is False
    assert (
        failed["checks"][
            "return_lift_vs_same_mechanism_control_at_least_1pct"
        ]
        is False
    )


def test_decision_reason_preserves_failed_gate() -> None:
    gate = {
        "passed": False,
        "checks": {
            "return_shortfall_vs_direct_within_3pct": False,
            "history_audit": True,
        },
    }

    reason = study.build_decision_reason(gate)

    assert "return_shortfall_vs_direct_within_3pct" in reason
    assert "归档且不注册" in reason
