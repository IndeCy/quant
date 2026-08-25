"""残差动量正式研究的风格残差与晋级门禁。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data.fund_portfolio import load_fund_portfolio_panel
from examples.factor_multifold_revalidation import FOLDS
from examples.factor_zoo_walk_forward_residual_metrics import (
    evaluate_single_candidate,
)
from runtime.paths import RuntimePaths


def build_style_residual(
    paths: RuntimePaths,
    annual: dict[str, dict[str, float]],
    latest_date: str,
    strategy_id: str,
) -> dict[str, Any]:
    """复用冻结走步口径，判断收益是否仍由中盘价差解释。"""
    years = list(range(2015, int(latest_date[:4]) + 1))
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        ["510300.SH", "510500.SH"],
        start_date="20140101",
        end_date=latest_date,
    )
    fund_annual = panel.adjusted_close.groupby(
        panel.adjusted_close.index.year
    ).apply(lambda frame: frame.iloc[-1] / frame.iloc[0] - 1.0)
    midcap_spread = (
        fund_annual["510500.SH"] - fund_annual["510300.SH"]
    ).reindex(years)
    excess = pd.Series(
        {
            int(year): float(values["excess_return"])
            for year, values in annual.items()
        }
    ).reindex(years)
    return evaluate_single_candidate(
        strategy_id,
        excess,
        midcap_spread,
    )


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
    style_residual: dict[str, Any],
) -> dict[str, Any]:
    """执行固定四折、执行成本与风格残差门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    checks = {
        "full_annual_return_at_least_8pct": (
            full["annualized_return"] >= 0.08
        ),
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_055": full["sharpe"] >= 0.55,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_30pct": (
            min(item["max_drawdown"] for item in folds) >= -0.30
        ),
        "median_fold_sharpe_at_least_035": (
            float(
                pd.Series([item["sharpe"] for item in folds]).median()
            ) >= 0.35
        ),
        "annual_turnover_below_10x": full["annual_turnover"] <= 10.0,
        "quality_correlation_at_most_075": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.75
        ),
        "walk_forward_midcap_residual_gate": bool(
            style_residual["gate_passed"]
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_folds": sum(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown": min(
            item["max_drawdown"] for item in folds
        ),
        "median_fold_sharpe": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        ),
    }
