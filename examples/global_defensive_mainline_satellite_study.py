"""全球防守核心与 A 股主线卫星固定 80/20 组合研究。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.global_defensive_mainline_satellite_report import render_report
from examples.quality_mainline_diversification_metrics import (
    build_annual_returns,
    build_drawdown_attribution,
    build_period_correlations,
    build_period_metrics,
)
from examples.quality_mainline_diversification_study import (
    AllocationRun,
    simulate_monthly_allocation,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "global_defensive_mainline_satellite_80_20_v2"
REPORT_PATH = Path(
    "docs/research/global-defensive-mainline-satellite-80-20-v2.md"
)
CORE_ID = "global_defensive_equal_v1"
SATELLITE_ID = "mainline_chain_factor_v1"
QUALITY_REFERENCE_ID = "quality_balanced_value_v1"
CORE_WEIGHT = 0.80
SATELLITE_WEIGHT = 0.20
ALLOCATION_COST_BPS = 10.0
STRESS_COST_BPS = 50.0
FOLDS = {
    "2020_2021": ("20200615", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球防守核心 × A股主线卫星 80/20 V2",
    category="portfolio_strategy",
    hypothesis=(
        "将高尾部风险但低相关的A股主线限制在20%卫星仓位，"
        "能否提升全球防守核心收益而不破坏回撤与Sharpe"
    ),
    definition={
        "sleeves": {
            "core": {"strategy_id": CORE_ID, "allocation": CORE_WEIGHT},
            "satellite": {
                "strategy_id": SATELLITE_ID,
                "allocation": SATELLITE_WEIGHT,
                "hard_weight_cap": SATELLITE_WEIGHT,
            },
        },
        "quality_independence_reference": QUALITY_REFERENCE_ID,
        "source": "monitoring_strategy_nav_daily_net_of_execution_cost",
        "history": {
            "alignment": "strict_inner_join_no_fill",
            "satellite_common_date_coverage_min": 0.999,
            "known_pre_registration_diagnostic": {
                "missing_from_core": ["20220329"],
                "reason": "source_calendar_difference_not_imputed",
            },
        },
        "allocation": {
            "weight_grid": False,
            "rebalance_signal": "month_end_close",
            "effective": "next_trading_day",
            "between_rebalances": "weights_drift_with_returns",
            "base_transfer_cost_bps": ALLOCATION_COST_BPS,
            "stress_transfer_cost_bps": STRESS_COST_BPS,
        },
        "folds": FOLDS,
        "frozen_gate": {
            "common_days_min": 1400,
            "sleeve_return_correlation_max": 0.35,
            "quality_return_correlation_max": 0.45,
            "full_annual_return_min": 0.10,
            "full_drawdown_floor": -0.18,
            "full_sharpe_min": 1.00,
            "full_calmar_min": 0.60,
            "return_lift_vs_core_min": 0.003,
            "sharpe_shortfall_vs_core_max": 0.10,
            "drawdown_worse_than_core_max": 0.03,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.20,
            "median_fold_sharpe_min": 0.75,
            "positive_years_min": 5,
            "allocation_turnover_max": 1.0,
            "base_cost_drag_max": 0.005,
            "stress_50bps_return_min": 0.095,
            "stress_50bps_drawdown_floor": -0.19,
            "stress_50bps_sharpe_min": 0.95,
            "worst_day_floor": -0.08,
            "expected_shortfall_95_floor": -0.025,
            "max_underwater_days": 504,
        },
        "no_bottom_strategy_change": True,
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_then_forward_portfolio_paper",
        "methodology_version": "fixed_core_satellite_multifold_tail_v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记固定定义和数据指纹，再读取完整净值历史。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, daily, annual, diagnostics = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, daily, annual, diagnostics)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    histories = load_strategy_histories(paths, as_of_date)
    audit = audit_common_history(histories)
    if not audit["passed"]:
        raise ValueError(f"strategy history audit failed: {audit}")
    common = histories[CORE_ID].merge(
        histories[SATELLITE_ID][["trade_date", "nav"]],
        on="trade_date",
        how="inner",
        suffixes=("_core", "_satellite"),
        validate="one_to_one",
    )
    allocation = simulate_monthly_allocation(
        common,
        core_weight=CORE_WEIGHT,
        satellite_weight=SATELLITE_WEIGHT,
        cost_bps=ALLOCATION_COST_BPS,
    )
    stress_allocation = simulate_monthly_allocation(
        common,
        core_weight=CORE_WEIGHT,
        satellite_weight=SATELLITE_WEIGHT,
        cost_bps=STRESS_COST_BPS,
    )
    periods = {
        name: (start, audit["end_date"] if end == "LATEST" else end)
        for name, (start, end) in FOLDS.items()
    }
    periods["full"] = (audit["start_date"], audit["end_date"])
    metrics = build_period_metrics(allocation.daily, periods)
    stress_metrics = build_period_metrics(stress_allocation.daily, periods)
    annual = build_annual_returns(allocation.daily)
    sleeve_correlations = build_period_correlations(allocation.daily, periods)
    correlations = {
        "sleeve_full": sleeve_correlations["full"],
        "quality_full": calculate_reference_correlation(
            allocation.daily,
            histories[QUALITY_REFERENCE_ID],
        ),
    }
    tail = build_tail_diagnostics(allocation.daily, annual)
    drawdown = build_drawdown_attribution(allocation.daily)
    cost_drag = calculate_cost_drag(allocation)
    stress_cost_drag = calculate_cost_drag(stress_allocation)
    gate = evaluate_gate(
        metrics,
        stress_metrics,
        annual,
        correlations,
        tail,
        audit,
        cost_drag=cost_drag,
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            metrics,
            stress_metrics,
            annual,
            correlations,
            tail,
            gate,
            audit,
            allocation_cost=allocation.total_cost,
            cost_drag=cost_drag,
            stress_cost_drag=stress_cost_drag,
        ),
        encoding="utf-8",
    )
    diagnostics = {
        "history_audit": audit,
        "correlations": correlations,
        "tail": tail,
        "drawdown_attribution": drawdown,
        "base_cost_drag": cost_drag,
        "stress_cost_drag": stress_cost_drag,
        "stress_full_metrics": stress_metrics["full"]["combined"],
    }
    result = {
        "portfolio_id": EXPERIMENT_ID,
        "as_of_date": as_of_date,
        "history_audit": audit,
        "period_metrics": metrics,
        "stress_period_metrics": stress_metrics,
        "annual_metrics": annual.to_dict("records"),
        "correlations": correlations,
        "tail_diagnostics": tail,
        "drawdown_attribution": drawdown,
        "allocation_total_cost": allocation.total_cost,
        "base_cost_drag": cost_drag,
        "stress_cost_drag": stress_cost_drag,
        "gate": gate,
        "decision": (
            "FORWARD_PORTFOLIO_PAPER_REQUIRED"
            if gate["passed"]
            else "REJECTED"
        ),
        "report_path": str(report_path),
        "reused": False,
    }
    return result, allocation.daily, annual, diagnostics


def load_strategy_histories(
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, pd.DataFrame]:
    """只读加载三个已登记策略的净成本事实曲线。"""
    histories: dict[str, pd.DataFrame] = {}
    uri = f"file:{paths.monitoring_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        for strategy_id in [CORE_ID, SATELLITE_ID, QUALITY_REFERENCE_ID]:
            histories[strategy_id] = pd.read_sql_query(
                """
                SELECT trade_date, strategy_id, nav, benchmark_id, benchmark_nav,
                       total_execution_cost
                FROM strategy_nav_daily
                WHERE strategy_id = ? AND trade_date <= ?
                ORDER BY trade_date
                """,
                connection,
                params=[strategy_id, as_of_date],
            )
    return histories


def audit_common_history(
    histories: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """拒绝缺日、重复、非正净值、异常成本或不同截止日。"""
    required = [CORE_ID, SATELLITE_ID, QUALITY_REFERENCE_ID]
    if any(histories.get(item, pd.DataFrame()).empty for item in required):
        return {"passed": False, "reason": "missing_strategy_history"}
    checks: dict[str, bool] = {}
    for strategy_id in required:
        frame = histories[strategy_id]
        checks[f"{strategy_id}_unique_dates"] = not frame[
            "trade_date"
        ].duplicated().any()
        checks[f"{strategy_id}_positive_nav"] = bool(
            frame["nav"].notna().all() and frame["nav"].gt(0).all()
        )
        checks[f"{strategy_id}_nonnegative_cost"] = bool(
            frame["total_execution_cost"].notna().all()
            and frame["total_execution_cost"].ge(0).all()
        )
    core = histories[CORE_ID]
    satellite = histories[SATELLITE_ID]
    quality = histories[QUALITY_REFERENCE_ID]
    common_dates = set(core["trade_date"]) & set(satellite["trade_date"])
    satellite_dates = set(satellite["trade_date"])
    coverage = len(common_dates) / len(satellite_dates)
    end_dates = {
        str(core["trade_date"].max()),
        str(satellite["trade_date"].max()),
        str(quality["trade_date"].max()),
    }
    checks.update(
        {
            "satellite_common_coverage_at_least_999pct": coverage >= 0.999,
            "same_end_date": len(end_dates) == 1,
            "expected_benchmark_identities": (
                set(core["benchmark_id"].astype(str)) == {"510300.SH"}
                and set(satellite["benchmark_id"].astype(str)) == {"000001.SH"}
                and set(quality["benchmark_id"].astype(str)) == {"510300"}
            ),
            "at_least_1400_common_days": len(common_dates) >= 1400,
        }
    )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "start_date": max(
            str(core["trade_date"].min()),
            str(satellite["trade_date"].min()),
        ),
        "end_date": min(
            str(core["trade_date"].max()),
            str(satellite["trade_date"].max()),
        ),
        "common_days": len(common_dates),
        "satellite_date_coverage": coverage,
    }


def calculate_reference_correlation(
    daily: pd.DataFrame,
    reference: pd.DataFrame,
) -> float:
    """计算组合与独立 Quality 参考的共同日收益相关性。"""
    quality = reference[["trade_date", "nav"]].sort_values("trade_date").copy()
    quality["quality_return"] = quality["nav"].astype(float).pct_change()
    candidate = daily[["trade_date", "portfolio_nav"]].copy()
    candidate["candidate_return"] = (
        candidate["portfolio_nav"].astype(float).pct_change()
    )
    merged = candidate.merge(
        quality[["trade_date", "quality_return"]],
        on="trade_date",
        how="inner",
        validate="one_to_one",
    ).dropna()
    if len(merged) < 252:
        raise ValueError("quality correlation requires at least 252 common returns")
    return float(
        merged[["candidate_return", "quality_return"]].corr().iloc[0, 1]
    )


def build_tail_diagnostics(
    daily: pd.DataFrame,
    annual: pd.DataFrame,
) -> dict[str, float | int]:
    """对净成本组合曲线计算最差日、ES 和最长水下期。"""
    nav = daily["portfolio_nav"].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    drawdown = nav / nav.cummax() - 1.0
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift(fill_value=False)).cumsum()
    lengths = underwater.groupby(groups).sum()
    return {
        "worst_day": float(returns.min()),
        "value_at_risk_95": threshold,
        "expected_shortfall_95": float(returns[returns.le(threshold)].mean()),
        "max_underwater_days": int(lengths.max()) if len(lengths) else 0,
        "positive_years": int(annual["combined_return"].gt(0).sum()),
        "year_count": int(len(annual)),
    }


def calculate_cost_drag(run: AllocationRun) -> float:
    """比较同一路径下毛净值与扣除组合调拨成本后的净值。"""
    daily = run.daily
    return float(daily["gross_nav"].iloc[-1] - daily["portfolio_nav"].iloc[-1])


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    stress_metrics: dict[str, dict[str, dict[str, float]]],
    annual: pd.DataFrame,
    correlations: dict[str, float],
    tail: dict[str, float | int],
    audit: dict[str, Any],
    *,
    cost_drag: float,
) -> dict[str, Any]:
    """按计算前冻结的收益、风险、独立性与成本门槛验收。"""
    full = metrics["full"]
    combined = full["combined"]
    core = full["core"]
    stress = stress_metrics["full"]["combined"]
    folds = [metrics[name]["combined"] for name in FOLDS]
    return_lift = combined["annualized_return"] - core["annualized_return"]
    sharpe_lift = combined["sharpe"] - core["sharpe"]
    drawdown_gap = (
        abs(combined["max_drawdown"]) - abs(core["max_drawdown"])
    )
    checks = {
        "history_audit": bool(audit["passed"]),
        "sleeve_correlation_at_most_035": (
            abs(correlations["sleeve_full"]) <= 0.35
        ),
        "quality_correlation_at_most_045": (
            abs(correlations["quality_full"]) <= 0.45
        ),
        "full_annual_return_at_least_10pct": (
            combined["annualized_return"] >= 0.10
        ),
        "full_drawdown_within_18pct": combined["max_drawdown"] >= -0.18,
        "full_sharpe_at_least_100": combined["sharpe"] >= 1.00,
        "full_calmar_at_least_060": combined["calmar"] >= 0.60,
        "full_positive_excess": combined["excess_return"] > 0,
        "return_lift_vs_core_at_least_03pct": return_lift >= 0.003,
        "sharpe_shortfall_vs_core_within_010": sharpe_lift >= -0.10,
        "drawdown_worse_than_core_within_3pct": drawdown_gap <= 0.03,
        "all_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_20pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.20,
        "median_fold_sharpe_at_least_075": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.75,
        "at_least_five_positive_years": int(
            annual["combined_return"].gt(0).sum()
        )
        >= 5,
        "allocation_turnover_below_1x": (
            combined["annual_turnover"] <= 1.0
        ),
        "base_cost_drag_within_05pct": cost_drag <= 0.005,
        "stress_50bps_return_at_least_95pct": (
            stress["annualized_return"] >= 0.095
        ),
        "stress_50bps_drawdown_within_19pct": (
            stress["max_drawdown"] >= -0.19
        ),
        "stress_50bps_sharpe_at_least_095": stress["sharpe"] >= 0.95,
        "worst_day_within_8pct": float(tail["worst_day"]) >= -0.08,
        "expected_shortfall_95_within_25pct": (
            float(tail["expected_shortfall_95"]) >= -0.025
        ),
        "max_underwater_within_504_days": (
            int(tail["max_underwater_days"]) <= 504
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "return_lift_vs_core": return_lift,
        "sharpe_lift_vs_core": sharpe_lift,
        "drawdown_gap_vs_core": drawdown_gap,
    }


def build_decision_reason(gate: dict[str, Any]) -> str:
    """把真实失败门槛写入研究登记。"""
    if gate["passed"]:
        return "80/20组合通过全部冻结门槛，仅允许组合级前向Paper"
    failed = [name for name, passed in gate["checks"].items() if not passed]
    return f"80/20组合未通过冻结门槛（{', '.join(failed)}），归档且不注册"


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    daily: pd.DataFrame,
    annual: pd.DataFrame,
    diagnostics: dict[str, Any],
) -> None:
    """保存完整净值、年度、诊断和成功/失败结论。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    daily_path = attempt.output_dir / "daily_nav.csv"
    annual_path = attempt.output_dir / "annual_metrics.csv"
    diagnostics_path = attempt.output_dir / "diagnostics.json"
    daily.to_csv(daily_path, index=False)
    annual.to_csv(annual_path, index=False)
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=build_decision_reason(result["gate"]),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "固定80/20研究报告"),
            ExperimentArtifact("daily_nav", daily_path, "组合及袖套每日净值"),
            ExperimentArtifact("annual_metrics", annual_path, "年度表现"),
            ExperimentArtifact(
                "diagnostics",
                diagnostics_path,
                "历史审计、相关性、尾部和成本压力诊断",
            ),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定监控事实库与三个只读策略声明。"""
    parts: list[str] = []
    for label, path in [
        ("monitoring", paths.monitoring_path),
        ("core_config", paths.config_dir / "strategies" / f"{CORE_ID}.json"),
        (
            "satellite_config",
            paths.config_dir / "strategies" / f"{SATELLITE_ID}.json",
        ),
        (
            "quality_config",
            paths.config_dir
            / "strategies"
            / f"{QUALITY_REFERENCE_ID}.json",
        ),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
