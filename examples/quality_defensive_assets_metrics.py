"""Quality防守资产研究的指标、相关性和固定门槛。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from examples.quality_factor_study_support import metric_summary, slice_result
from examples.quality_risk_layer_research import RiskLayerRun


FOLD_KEYS = ("2015_2017", "2018_2020", "2021_2023", "2024_latest")


def build_annual_metrics(
    runs: dict[str, RiskLayerRun],
    benchmark: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, dict[str, float]]]:
    """按自然年评价组合稳定性。"""
    return {
        strategy_id: {
            str(year): metric_summary(
                slice_result(
                    run.result,
                    f"{year}0101",
                    min(f"{year}1231", latest_date),
                ),
                benchmark,
            )
            for year in range(2015, int(latest_date[:4]) + 1)
        }
        for strategy_id, run in runs.items()
    }


def build_correlations(
    runs: dict[str, RiskLayerRun],
    *,
    core_id: str,
    defensive_id: str,
    blend_id: str,
) -> dict[str, float]:
    """计算防守袖套与核心、组合与核心的日收益相关性。"""
    returns = {
        key: value.result.daily_values.pct_change()
        for key, value in runs.items()
    }
    return {
        "defensive_core": float(returns[defensive_id].corr(returns[core_id])),
        "blend_core": float(returns[blend_id].corr(returns[core_id])),
        "blend_defensive": float(returns[blend_id].corr(returns[defensive_id])),
    }


def build_risk_path_diagnostics(
    runs: dict[str, RiskLayerRun],
    *,
    core_id: str,
    blend_id: str,
) -> dict[str, Any]:
    """定位核心与混合组合在2015年首次触发降仓的时间差。"""

    def summarize(run: RiskLayerRun) -> dict[str, Any]:
        exposure = run.exposure.sort_index()
        reduced = exposure.loc["2015"] < 1.0
        reduced_dates = reduced[reduced].index
        values = run.result.daily_values.sort_index()
        drawdown = values / values.cummax() - 1.0
        valley = drawdown.idxmin()
        peak = values.loc[:valley].idxmax()
        return {
            "first_reduced_date_2015": (
                reduced_dates[0].strftime("%Y%m%d")
                if len(reduced_dates)
                else None
            ),
            "reduced_days_2015": int(reduced.sum()),
            "drawdown_peak": peak.strftime("%Y%m%d"),
            "drawdown_valley": valley.strftime("%Y%m%d"),
        }

    core = summarize(runs[core_id])
    blend = summarize(runs[blend_id])
    core_date = pd.Timestamp(core["first_reduced_date_2015"])
    blend_date = pd.Timestamp(blend["first_reduced_date_2015"])
    trade_dates = runs[core_id].result.daily_values.index
    delay = int(((trade_dates > core_date) & (trade_dates <= blend_date)).sum())
    return {
        "core": core,
        "blend": blend,
        "blend_trigger_delay_trading_days": delay,
    }


def evaluate_gate(
    blend: dict[str, dict[str, float]],
    core: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    correlations: dict[str, float],
) -> dict[str, Any]:
    """固定绝对门槛与相对核心改善门槛必须同时满足。"""
    full = blend["full"]
    core_full = core["full"]
    folds = [blend[key] for key in FOLD_KEYS]
    checks = {
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_calmar_at_least_040": full["calmar"] >= 0.40,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_25pct": (
            min(item["max_drawdown"] for item in folds) >= -0.25
        ),
        "median_fold_sharpe_at_least_035": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.35
        ),
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "drawdown_improves_core_by_3pct": (
            full["max_drawdown"] >= core_full["max_drawdown"] + 0.03
        ),
        "return_within_2_5pct_of_core": (
            full["annualized_return"] >= core_full["annualized_return"] - 0.025
        ),
        "sharpe_not_below_core": full["sharpe"] >= core_full["sharpe"],
        "defensive_correlation_to_core_at_most_030": (
            abs(correlations["defensive_core"]) <= 0.30
        ),
        "at_least_nine_positive_years": (
            sum(item["annualized_return"] > 0 for item in annual.values()) >= 9
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "drawdown_improvement": float(
            full["max_drawdown"] - core_full["max_drawdown"]
        ),
        "annual_return_shortfall": float(
            core_full["annualized_return"] - full["annualized_return"]
        ),
    }


def evaluate_scoped_gate(
    scoped: dict[str, dict[str, float]],
    core: dict[str, dict[str, float]],
    whole_overlay: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """冻结袖套级风险预算的绝对和相对晋级门槛。"""
    full = scoped["full"]
    core_full = core["full"]
    whole_full = whole_overlay["full"]
    folds = [scoped[key] for key in FOLD_KEYS]
    checks = {
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_calmar_at_least_040": full["calmar"] >= 0.40,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_25pct": (
            min(item["max_drawdown"] for item in folds) >= -0.25
        ),
        "median_fold_sharpe_at_least_035": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.35
        ),
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "drawdown_improves_core_by_3pct": (
            full["max_drawdown"] >= core_full["max_drawdown"] + 0.03
        ),
        "drawdown_improves_whole_overlay_by_5pct": (
            full["max_drawdown"] >= whole_full["max_drawdown"] + 0.05
        ),
        "return_within_2_5pct_of_core": (
            full["annualized_return"] >= core_full["annualized_return"] - 0.025
        ),
        "sharpe_not_below_core": full["sharpe"] >= core_full["sharpe"],
        "at_least_nine_positive_years": (
            sum(item["annualized_return"] > 0 for item in annual.values()) >= 9
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "drawdown_improvement_vs_core": float(
            full["max_drawdown"] - core_full["max_drawdown"]
        ),
        "drawdown_improvement_vs_whole_overlay": float(
            full["max_drawdown"] - whole_full["max_drawdown"]
        ),
        "annual_return_shortfall_vs_core": float(
            core_full["annualized_return"] - full["annualized_return"]
        ),
    }


def evaluate_robustness_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, dict[str, float]]],
    *,
    baseline_id: str,
    neighborhood_ids: tuple[str, ...],
    cost_stress_ids: tuple[str, ...],
    delay_id: str,
    single_asset_ids: tuple[str, ...],
) -> dict[str, Any]:
    """不选择最优版本，只验证冻结主方案是否形成稳定平台。"""
    baseline = metrics[baseline_id]["full"]
    baseline_folds = [metrics[baseline_id][key] for key in FOLD_KEYS]

    def all_meet(
        scenario_ids: tuple[str, ...],
        *,
        annual_return: float,
        drawdown: float,
        sharpe: float,
    ) -> bool:
        return all(
            metrics[scenario_id]["full"]["annualized_return"] >= annual_return
            and metrics[scenario_id]["full"]["max_drawdown"] >= drawdown
            and metrics[scenario_id]["full"]["sharpe"] >= sharpe
            for scenario_id in scenario_ids
        )

    all_scenarios = (
        baseline_id,
        *neighborhood_ids,
        *cost_stress_ids,
        delay_id,
        *single_asset_ids,
    )
    checks = {
        "baseline_annual_return_at_least_10pct": (
            baseline["annualized_return"] >= 0.10
        ),
        "baseline_drawdown_within_25pct": baseline["max_drawdown"] >= -0.25,
        "baseline_sharpe_at_least_065": baseline["sharpe"] >= 0.65,
        "baseline_calmar_at_least_040": baseline["calmar"] >= 0.40,
        "baseline_positive_excess": baseline["excess_return"] > 0,
        "all_baseline_folds_positive": all(
            item["annualized_return"] > 0 for item in baseline_folds
        ),
        "at_least_nine_positive_years": (
            sum(
                item["annualized_return"] > 0
                for item in annual[baseline_id].values()
            )
            >= 9
        ),
        "neighbor_weights_form_platform": all_meet(
            neighborhood_ids,
            annual_return=0.09,
            drawdown=-0.25,
            sharpe=0.60,
        ),
        "execution_cost_stress_survives": all_meet(
            cost_stress_ids,
            annual_return=0.09,
            drawdown=-0.25,
            sharpe=0.60,
        ),
        "one_day_extra_delay_survives": all_meet(
            (delay_id,),
            annual_return=0.09,
            drawdown=-0.25,
            sharpe=0.60,
        ),
        "single_defensive_assets_survive": all_meet(
            single_asset_ids,
            annual_return=0.08,
            drawdown=-0.30,
            sharpe=0.50,
        ),
        "all_scenarios_turnover_below_8x": all(
            metrics[scenario_id]["full"]["annual_turnover"] <= 8.0
            for scenario_id in all_scenarios
        ),
    }
    full_metrics = {
        scenario_id: metrics[scenario_id]["full"]
        for scenario_id in all_scenarios
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "min_annualized_return": min(
            item["annualized_return"] for item in full_metrics.values()
        ),
        "worst_max_drawdown": min(
            item["max_drawdown"] for item in full_metrics.values()
        ),
        "min_sharpe": min(item["sharpe"] for item in full_metrics.values()),
    }
