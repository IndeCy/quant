"""Quality 防御与主线链动组合构建测试。"""

from __future__ import annotations

import pandas as pd

from examples import quality_mainline_diversification_study as study


def test_monthly_allocation_rebalances_on_next_month_first_trade_day() -> None:
    """月末信号只能在下月首个交易日恢复 70/30。"""
    common = pd.DataFrame(
        {
            "trade_date": ["20240130", "20240131", "20240201", "20240202"],
            "nav_core": [1.0, 1.1, 1.1, 1.1],
            "nav_satellite": [1.0, 1.0, 1.0, 1.0],
            "benchmark_nav": [1.0, 1.0, 1.0, 1.0],
        }
    )

    run = study.simulate_monthly_allocation(
        common,
        core_weight=0.70,
        satellite_weight=0.30,
        cost_bps=10.0,
    )

    rows = run.daily.set_index("trade_date")
    assert rows.loc["20240131", "rebalance"] == False
    assert rows.loc["20240201", "rebalance"] == True
    assert rows.loc["20240201", "core_weight_open"] == 0.70
    assert rows.loc["20240201", "allocation_turnover"] > 0


def test_monthly_allocation_allows_weights_to_drift() -> None:
    """月内不能每日强行重置权重。"""
    common = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103", "20240104"],
            "nav_core": [1.0, 1.1, 1.21],
            "nav_satellite": [1.0, 1.0, 1.0],
            "benchmark_nav": [1.0, 1.0, 1.0],
        }
    )

    run = study.simulate_monthly_allocation(
        common,
        core_weight=0.70,
        satellite_weight=0.30,
        cost_bps=10.0,
    )

    assert run.daily.iloc[-1]["core_weight_close"] > 0.70
    assert run.daily["allocation_turnover"].sum() == 0.0


def test_diversification_gate_requires_sharpe_improvement() -> None:
    """组合收益提高但 Sharpe 下降时仍不能晋级。"""
    combined = {
        "annualized_return": 0.12,
        "max_drawdown": -0.20,
        "sharpe": 0.60,
        "calmar": 0.60,
        "excess_return": 0.20,
        "annual_turnover": 0.20,
    }
    core = {**combined, "annualized_return": 0.10, "sharpe": 0.70}
    satellite = dict(combined)
    metrics = {
        name: {
            "combined": dict(combined),
            "core": dict(core),
            "satellite": dict(satellite),
        }
        for name in [*study.FOLDS, "full"]
    }

    gate = study.evaluate_gate(
        metrics,
        {**{name: 0.40 for name in study.FOLDS}, "full": 0.40},
        {"passed": True},
    )

    assert gate["passed"] is False
    assert gate["checks"]["combined_sharpe_at_least_core"] is False


def test_period_metrics_uses_each_period_turnover() -> None:
    """分段换手率必须按该段实际调拨计算。"""
    daily = pd.DataFrame(
        {
            "trade_date": ["20210101", "20210102", "20220101", "20220102"],
            "portfolio_nav": [1.0, 1.1, 1.1, 1.2],
            "core_nav": [1.0, 1.1, 1.1, 1.2],
            "satellite_nav": [1.0, 1.1, 1.1, 1.2],
            "benchmark_nav": [1.0, 1.0, 1.0, 1.0],
            "allocation_turnover": [0.0, 0.01, 0.0, 0.02],
        }
    )

    metrics = study.build_period_metrics(
        daily,
        {
            "2021": ("20210101", "20211231"),
            "2022": ("20220101", "20221231"),
        },
    )

    assert metrics["2021"]["combined"]["annual_turnover"] == 2.52
    assert metrics["2022"]["combined"]["annual_turnover"] == 5.04


def test_decision_reason_names_failed_frozen_gate() -> None:
    """归档理由不能误写成没有改善风险收益比。"""
    gate = {
        "passed": False,
        "checks": {
            "combined_sharpe_at_least_core": True,
            "all_folds_positive": False,
        },
    }

    reason = study.build_decision_reason(gate)

    assert "all_folds_positive" in reason
    assert "未提升核心风险收益比" not in reason
