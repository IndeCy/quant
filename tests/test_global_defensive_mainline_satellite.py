"""全球防守核心与主线卫星固定 80/20 研究测试。"""

from __future__ import annotations

import pandas as pd

from examples import global_defensive_mainline_satellite_study as study


def _history(
    strategy_id: str,
    dates: list[str],
    *,
    benchmark: str = "510300",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": dates,
            "strategy_id": strategy_id,
            "nav": [1.0 + index * 0.001 for index in range(len(dates))],
            "benchmark_id": benchmark,
            "benchmark_nav": [1.0] * len(dates),
            "total_execution_cost": [0.0] * len(dates),
        }
    )


def _passing_metrics() -> dict[str, dict[str, dict[str, float]]]:
    combined = {
        "annualized_return": 0.12,
        "max_drawdown": -0.12,
        "sharpe": 1.20,
        "calmar": 1.00,
        "excess_return": 0.20,
        "annual_turnover": 0.20,
    }
    core = {
        **combined,
        "annualized_return": 0.115,
        "max_drawdown": -0.11,
        "sharpe": 1.25,
    }
    return {
        name: {
            "combined": dict(combined),
            "core": dict(core),
            "satellite": dict(combined),
        }
        for name in [*study.FOLDS, "full"]
    }


def test_research_spec_freezes_weight_without_grid() -> None:
    """20% 卫星权重必须是硬上限且禁止结果后选参。"""
    definition = study.RESEARCH_SPEC.definition

    assert definition["sleeves"]["core"]["allocation"] == 0.80
    assert definition["sleeves"]["satellite"]["allocation"] == 0.20
    assert definition["sleeves"]["satellite"]["hard_weight_cap"] == 0.20
    assert definition["allocation"]["weight_grid"] is False
    assert definition["parameters_fixed_before_backtest"] is True
    assert (
        definition["promotion_scope"]
        == "research_only_then_forward_portfolio_paper"
    )


def test_history_audit_rejects_different_end_dates() -> None:
    """三个参考策略截止日不同不能静默截断后晋级。"""
    dates = [
        (pd.Timestamp("2020-01-01") + pd.Timedelta(days=index)).strftime(
            "%Y%m%d"
        )
        for index in range(1401)
    ]
    histories = {
        study.CORE_ID: _history(study.CORE_ID, dates),
        study.SATELLITE_ID: _history(study.SATELLITE_ID, dates),
        study.QUALITY_REFERENCE_ID: _history(
            study.QUALITY_REFERENCE_ID,
            dates[:-1],
        ),
    }

    audit = study.audit_common_history(histories)

    assert audit["passed"] is False
    assert audit["checks"]["same_end_date"] is False


def test_gate_enforces_tail_and_stress_thresholds() -> None:
    """平均收益通过时仍必须通过最差日、ES 和 50bps 压力。"""
    metrics = _passing_metrics()
    stress = _passing_metrics()
    annual = pd.DataFrame(
        {"combined_return": [0.1, 0.1, 0.1, 0.1, 0.1]}
    )
    correlations = {"sleeve_full": 0.10, "quality_full": 0.20}
    tail = {
        "worst_day": -0.05,
        "expected_shortfall_95": -0.02,
        "max_underwater_days": 200,
    }

    passed = study.evaluate_gate(
        metrics,
        stress,
        annual,
        correlations,
        tail,
        {"passed": True},
        cost_drag=0.001,
    )
    assert passed["passed"] is True

    tail["expected_shortfall_95"] = -0.03
    stress["full"]["combined"]["sharpe"] = 0.80
    failed = study.evaluate_gate(
        metrics,
        stress,
        annual,
        correlations,
        tail,
        {"passed": True},
        cost_drag=0.001,
    )

    assert failed["passed"] is False
    assert (
        failed["checks"]["expected_shortfall_95_within_25pct"] is False
    )
    assert failed["checks"]["stress_50bps_sharpe_at_least_095"] is False


def test_reference_correlation_uses_common_daily_returns() -> None:
    """独立性必须在共同交易日的净值收益上计算。"""
    dates = pd.bdate_range("2024-01-02", periods=300)
    values = pd.Series(range(300), dtype=float)
    candidate_nav = (1.0 + values * 0.001).tolist()
    reference_nav = (1.0 + values * 0.002).tolist()
    daily = pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "portfolio_nav": candidate_nav,
        }
    )
    reference = pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "nav": reference_nav,
        }
    )

    correlation = study.calculate_reference_correlation(daily, reference)

    assert correlation > 0.99


def test_decision_reason_lists_failed_frozen_gate() -> None:
    gate = {
        "passed": False,
        "checks": {
            "full_sharpe_at_least_100": False,
            "history_audit": True,
        },
    }

    reason = study.build_decision_reason(gate)

    assert "full_sharpe_at_least_100" in reason
    assert "归档且不注册" in reason
