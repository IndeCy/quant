"""Quality Balanced Value 稳健性门禁测试。"""

from __future__ import annotations

from examples.quality_balanced_value_robustness_metrics import (
    evaluate_robustness_gate,
    positive_year_concentration,
    summarize_window_stability,
)


def test_positive_year_concentration_uses_log_wealth() -> None:
    """年度贡献应按复利对数收益计算，不直接相加百分比。"""
    result = positive_year_concentration(
        {
            "2020": {"annualized_return": 1.0},
            "2021": {"annualized_return": 0.5},
            "2022": {"annualized_return": -0.2},
        }
    )

    assert result["positive_year_count"] == 2
    assert 0.60 < result["top1_positive_log_contribution"] < 0.65


def test_window_summary_counts_positive_return_and_excess() -> None:
    """三年窗口的绝对收益和超额收益必须分别统计。"""
    summary = summarize_window_stability(
        {
            "A": {
                "annualized_return": 0.10,
                "excess_return": 0.02,
                "sharpe": 0.8,
                "max_drawdown": -0.20,
            },
            "B": {
                "annualized_return": -0.02,
                "excess_return": 0.03,
                "sharpe": 0.1,
                "max_drawdown": -0.40,
            },
        }
    )

    assert summary["positive_return_share"] == 0.5
    assert summary["positive_excess_share"] == 1.0
    assert summary["worst_drawdown"] == -0.40


def test_robustness_gate_rejects_first_year_dependency() -> None:
    """全期合格但剔除首年失败时不得宣称稳健。"""
    gate = evaluate_robustness_gate(
        full_metrics={
            "annualized_return": 0.13,
            "max_drawdown": -0.25,
            "sharpe": 0.70,
        },
        without_2015_metrics={
            "annualized_return": 0.04,
            "max_drawdown": -0.25,
            "sharpe": 0.40,
        },
        cost_20bps_metrics={
            "annualized_return": 0.11,
            "max_drawdown": -0.27,
            "sharpe": 0.62,
        },
        window_summary={
            "positive_return_share": 0.80,
            "positive_excess_share": 0.60,
            "median_sharpe": 0.50,
            "worst_drawdown": -0.30,
        },
        concentration={
            "positive_year_count": 8,
            "top1_positive_log_contribution": 0.30,
        },
    )

    assert gate["passed"] is False
    assert gate["checks"][
        "without_2015_annual_return_at_least_8pct"
    ] is False
