"""Quality Balanced Value 稳健性指标和预注册门禁。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def positive_year_concentration(
    annual_metrics: dict[str, dict[str, float]],
) -> dict[str, float]:
    """用正年度对数收益衡量最好一年对财富增长的集中度。"""
    positive_logs = {
        year: math.log1p(float(metrics["annualized_return"]))
        for year, metrics in annual_metrics.items()
        if float(metrics["annualized_return"]) > 0
    }
    total = sum(positive_logs.values())
    ordered = sorted(positive_logs.values(), reverse=True)
    return {
        "positive_year_count": float(len(positive_logs)),
        "top1_positive_log_contribution": (
            ordered[0] / total if total > 0 and ordered else 0.0
        ),
        "top3_positive_log_contribution": (
            sum(ordered[:3]) / total if total > 0 else 0.0
        ),
    }


def summarize_window_stability(
    window_metrics: dict[str, dict[str, float]],
) -> dict[str, float]:
    """汇总完整三年窗口的正收益比例和风险中位数。"""
    if not window_metrics:
        raise ValueError("three-year window metrics are required")
    frame = pd.DataFrame.from_dict(window_metrics, orient="index")
    return {
        "window_count": float(len(frame)),
        "positive_return_share": float(
            frame["annualized_return"].gt(0).mean()
        ),
        "positive_excess_share": float(
            frame["excess_return"].gt(0).mean()
        ),
        "median_annualized_return": float(
            frame["annualized_return"].median()
        ),
        "median_sharpe": float(frame["sharpe"].median()),
        "worst_drawdown": float(frame["max_drawdown"].min()),
    }


def evaluate_robustness_gate(
    *,
    full_metrics: dict[str, float],
    without_2015_metrics: dict[str, float],
    cost_20bps_metrics: dict[str, float],
    window_summary: dict[str, float],
    concentration: dict[str, float],
) -> dict[str, Any]:
    """执行研究前冻结的首年依赖、窗口稳定和成本压力门槛。"""
    checks = {
        "full_annual_return_at_least_10pct": (
            full_metrics["annualized_return"] >= 0.10
        ),
        "full_drawdown_within_30pct": (
            full_metrics["max_drawdown"] >= -0.30
        ),
        "full_sharpe_at_least_065": full_metrics["sharpe"] >= 0.65,
        "without_2015_annual_return_at_least_8pct": (
            without_2015_metrics["annualized_return"] >= 0.08
        ),
        "without_2015_drawdown_within_30pct": (
            without_2015_metrics["max_drawdown"] >= -0.30
        ),
        "without_2015_sharpe_at_least_055": (
            without_2015_metrics["sharpe"] >= 0.55
        ),
        "three_year_positive_share_at_least_75pct": (
            window_summary["positive_return_share"] >= 0.75
        ),
        "three_year_positive_excess_share_at_least_50pct": (
            window_summary["positive_excess_share"] >= 0.50
        ),
        "three_year_median_sharpe_at_least_035": (
            window_summary["median_sharpe"] >= 0.35
        ),
        "three_year_worst_drawdown_within_35pct": (
            window_summary["worst_drawdown"] >= -0.35
        ),
        "cost_20bps_annual_return_at_least_10pct": (
            cost_20bps_metrics["annualized_return"] >= 0.10
        ),
        "cost_20bps_drawdown_within_30pct": (
            cost_20bps_metrics["max_drawdown"] >= -0.30
        ),
        "cost_20bps_sharpe_at_least_060": (
            cost_20bps_metrics["sharpe"] >= 0.60
        ),
        "top_positive_year_contribution_at_most_40pct": (
            concentration["top1_positive_log_contribution"] <= 0.40
        ),
        "at_least_seven_positive_years": (
            concentration["positive_year_count"] >= 7
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}
