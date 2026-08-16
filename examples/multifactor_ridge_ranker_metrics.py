"""多因子 Ridge 研究的指标、稳定性和晋级门槛。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from examples.quality_factor_study_support import metric_summary, slice_result
from examples.quality_risk_layer_research import RiskLayerRun


FIRST_TEST_YEAR = 2019
ML_ID = "multifactor_ridge_walk_forward_v1"
EQUAL_ID = "five_factor_equal_weight_control"
QUALITY_ID = "quality_balanced_value_control"


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    prediction: dict[str, float],
    coefficients: dict[str, dict[str, float]],
    comparison: dict[str, dict[str, float]],
    quality_correlation: float,
    quality_overlap: float,
) -> dict[str, Any]:
    """执行预测、绩效、基线增量和可解释性门槛。"""
    full = metrics["full_oos"]
    equal = comparison[EQUAL_ID]
    quality = comparison[QUALITY_ID]
    folds = [
        metrics[key]
        for key in ["2019_2021", "2022_2023", "2024_latest"]
    ]
    stable_features = sum(
        item["positive_share"] >= 0.75
        for item in coefficients.values()
    )
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    checks = {
        "mean_rank_ic_at_least_002": prediction["mean_rank_ic"] >= 0.02,
        "positive_ic_months_at_least_55pct": (
            prediction["positive_ic_ratio"] >= 0.55
        ),
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_calmar_at_least_030": full["calmar"] >= 0.30,
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "at_least_six_positive_years": positive_years >= 6,
        "all_three_periods_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "median_period_sharpe_at_least_050": (
            float(pd.Series([item["sharpe"] for item in folds]).median())
            >= 0.50
        ),
        "equal_control_sharpe_improves_005": (
            full["sharpe"] - equal["sharpe"] >= 0.05
        ),
        "equal_control_return_shortfall_within_2pct": (
            equal["annualized_return"] - full["annualized_return"] <= 0.02
        ),
        "equal_control_drawdown_deterioration_within_3pct": (
            equal["max_drawdown"] - full["max_drawdown"] <= 0.03
        ),
        "equal_control_turnover_within_125x": (
            full["annual_turnover"]
            <= equal["annual_turnover"] * 1.25
        ),
        "quality_sharpe_shortfall_within_005": (
            quality["sharpe"] - full["sharpe"] <= 0.05
        ),
        "quality_return_shortfall_within_2pct": (
            quality["annualized_return"] - full["annualized_return"] <= 0.02
        ),
        "quality_drawdown_deterioration_within_3pct": (
            quality["max_drawdown"] - full["max_drawdown"] <= 0.03
        ),
        "quality_return_correlation_at_most_085": (
            abs(quality_correlation) <= 0.85
        ),
        "quality_holding_overlap_at_most_70pct": quality_overlap <= 0.70,
        "at_least_four_stable_positive_features": stable_features >= 4,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
        "stable_positive_features": stable_features,
    }


def summarize_predictions(predictions: pd.DataFrame) -> dict[str, float]:
    """按月计算样本外RankIC和正IC月份占比。"""
    monthly = pd.Series(
        {
            str(date): group["prediction"].corr(
                group["forward_rank"],
                method="spearman",
            )
            for date, group in predictions.groupby("signal_date", sort=True)
        },
        dtype=float,
    ).dropna()
    return {
        "month_count": int(len(monthly)),
        "mean_rank_ic": float(monthly.mean()),
        "ic_std": float(monthly.std(ddof=1)),
        "positive_ic_ratio": float(monthly.gt(0).mean()),
    }


def summarize_coefficients(
    coefficients: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """衡量各特征在逐年重训中的方向稳定性。"""
    latest_year = int(coefficients["test_year"].max())
    return {
        str(feature): {
            "mean": float(group["coefficient"].mean()),
            "positive_share": float(group["coefficient"].gt(0).mean()),
            "latest": float(
                group.loc[
                    group["test_year"].eq(latest_year),
                    "coefficient",
                ].iloc[0]
            ),
        }
        for feature, group in coefficients.groupby("feature", sort=True)
    }


def average_holding_overlap(
    left: dict[str, list[str]],
    right: dict[str, list[str]],
) -> float:
    """按候选持仓占比计算逐月平均重叠。"""
    common_dates = sorted(set(left) & set(right))
    if not common_dates:
        return 1.0
    values = [
        len(set(left[date]) & set(right[date]))
        / max(len(left[date]), 1)
        for date in common_dates
    ]
    return float(pd.Series(values).mean())


def build_annual_metrics(
    run: RiskLayerRun,
    benchmark: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, float]]:
    """输出2019年至数据截止年的年度指标。"""
    return {
        str(year): metric_summary(
            slice_result(
                run.result,
                f"{year}0101",
                min(f"{year}1231", latest_date),
            ),
            benchmark,
        )
        for year in range(FIRST_TEST_YEAR, int(latest_date[:4]) + 1)
    }


def build_failure_attribution(
    buckets: pd.DataFrame,
    coefficients: dict[str, dict[str, float]],
    comparison: dict[str, dict[str, float]],
) -> dict[str, float | bool]:
    """量化Top尾部反转、低波支配和换手成本放大。"""
    ordered = buckets.sort_values("bucket")
    top = ordered.iloc[-1]
    middle = ordered[
        ordered["bucket"].astype(int).between(4, 8, inclusive="both")
    ]
    absolute_total = sum(
        abs(float(item["mean"])) for item in coefficients.values()
    )
    low_vol_share = (
        abs(float(coefficients["low_volatility_60d"]["mean"]))
        / absolute_total
        if absolute_total > 0
        else 0.0
    )
    candidate = comparison[ML_ID]
    equal = comparison[EQUAL_ID]
    return {
        "top_bucket_forward_return": float(top["average_forward_return"]),
        "middle_bucket_average_return": float(
            middle["average_forward_return"].mean()
        ),
        "top_tail_return_gap": float(
            top["average_forward_return"]
            - middle["average_forward_return"].mean()
        ),
        "top_tail_weaker_than_middle": bool(
            top["average_forward_return"]
            < middle["average_forward_return"].mean()
        ),
        "low_vol_absolute_coefficient_share": low_vol_share,
        "turnover_multiplier_vs_equal": float(
            candidate["annual_turnover"] / equal["annual_turnover"]
        ),
        "execution_cost_gap_vs_equal": float(
            candidate["execution_cost_impact"]
            - equal["execution_cost_impact"]
        ),
    }
