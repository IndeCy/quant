"""Quality 防御核心与主线链动卫星的固定 70/30 组合研究。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.quality_mainline_diversification_metrics import (
    build_annual_returns,
    build_drawdown_attribution,
    build_period_correlations,
    build_period_metrics,
)
from examples.quality_mainline_diversification_report import render_report
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "quality_defensive_mainline_70_30_v1"
REPORT_PATH = Path("docs/research/quality-defensive-mainline-70-30-v1.md")
CORE_ID = "quality_defensive_assets_core_scoped_70_15_15_v2"
SATELLITE_ID = "mainline_chain_factor_v1"
CORE_WEIGHT = 0.70
SATELLITE_WEIGHT = 0.30
ALLOCATION_COST_BPS = 10.0
FOLDS = {
    "2020_2021": ("20200615", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality 防御核心 × 主线链动 70/30 V1",
    category="portfolio_construction",
    hypothesis="主线链动作为30%卫星能否提升Quality防御核心收益而不显著破坏回撤和Sharpe",
    definition={
        "sleeves": {
            "core": {"strategy_id": CORE_ID, "allocation": CORE_WEIGHT},
            "satellite": {
                "strategy_id": SATELLITE_ID,
                "allocation": SATELLITE_WEIGHT,
            },
        },
        "source": "monitoring_strategy_nav_daily_net_of_execution_cost",
        "history": "strict_common_dates_only_no_backfill",
        "allocation": {
            "rebalance_signal": "month_end_close",
            "effective": "next_trading_day",
            "between_rebalances": "weights_drift_with_returns",
            "transfer_cost_bps": ALLOCATION_COST_BPS,
        },
        "benchmark": "core_510300_adjusted_nav",
        "folds": FOLDS,
        "frozen_gate": {
            "common_history_coverage": 1.0,
            "sleeve_return_correlation_max": 0.75,
            "combined_annual_return_at_least_core": True,
            "combined_sharpe_at_least_core": True,
            "combined_drawdown_worse_than_core_max": 0.03,
            "combined_drawdown_floor": -0.25,
            "combined_positive_excess": True,
            "all_folds_positive": True,
            "allocation_turnover_max": 1.0,
        },
        "no_factor_or_strategy_change": True,
        "parameters_fixed_before_backtest": True,
        "methodology_version": "portfolio_multifold_v1_1",
    },
)


@dataclass(frozen=True)
class AllocationRun:
    """组合级月度调拨结果。"""

    daily: pd.DataFrame
    annual_turnover: float
    total_cost: float


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """申请研究指纹后才读取完整策略历史。"""
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
        result, daily, annual = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, daily, annual)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """严格按共同日期对齐两个净成本策略资产。"""
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
    daily = allocation.daily
    periods = {
        name: (start, audit["end_date"] if end == "LATEST" else end)
        for name, (start, end) in FOLDS.items()
    }
    periods["full"] = (audit["start_date"], audit["end_date"])
    metrics = build_period_metrics(daily, periods)
    correlations = build_period_correlations(daily, periods)
    annual = build_annual_returns(daily)
    drawdown_attribution = build_drawdown_attribution(daily)
    gate = evaluate_gate(metrics, correlations, audit)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            metrics,
            annual,
            correlations,
            drawdown_attribution,
            gate,
            audit,
            allocation.total_cost,
        ),
        encoding="utf-8",
    )
    result = {
        "portfolio_id": EXPERIMENT_ID,
        "as_of_date": as_of_date,
        "history_audit": audit,
        "period_metrics": metrics,
        "return_correlations": correlations,
        "drawdown_attribution": drawdown_attribution,
        "allocation_total_cost": allocation.total_cost,
        "gate": gate,
        "decision": "FORWARD_PORTFOLIO_PAPER_REQUIRED" if gate["passed"] else "REJECTED",
        "report_path": str(report_path),
        "reused": False,
    }
    return result, daily, annual


def load_strategy_histories(
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, pd.DataFrame]:
    """从统一监控事实表读取净成本策略曲线。"""
    histories: dict[str, pd.DataFrame] = {}
    with sqlite3.connect(paths.monitoring_path) as connection:
        for strategy_id in [CORE_ID, SATELLITE_ID]:
            frame = pd.read_sql_query(
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
            histories[strategy_id] = frame
    return histories


def audit_common_history(
    histories: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """禁止补齐缺日、未来填充或混用非正净值。"""
    core = histories.get(CORE_ID, pd.DataFrame()).copy()
    satellite = histories.get(SATELLITE_ID, pd.DataFrame()).copy()
    if core.empty or satellite.empty:
        return {"passed": False, "reason": "missing_strategy_history"}
    for frame in [core, satellite]:
        if frame["trade_date"].duplicated().any():
            return {"passed": False, "reason": "duplicate_trade_date"}
        if frame["nav"].isna().any() or frame["nav"].le(0).any():
            return {"passed": False, "reason": "invalid_nav"}
    common_dates = set(core["trade_date"]) & set(satellite["trade_date"])
    satellite_dates = set(satellite["trade_date"])
    coverage = len(common_dates) / len(satellite_dates)
    common_start = max(str(core["trade_date"].min()), str(satellite["trade_date"].min()))
    common_end = min(str(core["trade_date"].max()), str(satellite["trade_date"].max()))
    checks = {
        "full_satellite_date_coverage": math.isclose(coverage, 1.0),
        "same_end_date": str(core["trade_date"].max())
        == str(satellite["trade_date"].max()),
        "core_benchmark_is_510300": set(core["benchmark_id"].astype(str))
        == {"510300"},
        "at_least_1000_common_days": len(common_dates) >= 1000,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "start_date": common_start,
        "end_date": common_end,
        "common_days": len(common_dates),
        "satellite_date_coverage": coverage,
    }


def simulate_monthly_allocation(
    common: pd.DataFrame,
    *,
    core_weight: float,
    satellite_weight: float,
    cost_bps: float,
) -> AllocationRun:
    """月末信号于次月首个交易日调拨，月内权重自然漂移。"""
    if not math.isclose(core_weight + satellite_weight, 1.0):
        raise ValueError("sleeve weights must sum to one")
    if common.empty or cost_bps < 0:
        raise ValueError("invalid allocation inputs")
    frame = common.sort_values("trade_date").copy()
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    frame["core_return"] = frame["nav_core"].astype(float).pct_change().fillna(0.0)
    frame["satellite_return"] = (
        frame["nav_satellite"].astype(float).pct_change().fillna(0.0)
    )
    frame["benchmark_nav"] = (
        frame["benchmark_nav"].astype(float)
        / float(frame["benchmark_nav"].astype(float).iloc[0])
    )
    target = {"core": core_weight, "satellite": satellite_weight}
    weights = dict(target)
    portfolio_nav = 1.0
    gross_nav = 1.0
    total_cost = 0.0
    records: list[dict[str, Any]] = []
    previous_month = frame.iloc[0]["date"].to_period("M")
    for index, row in frame.iterrows():
        current_month = row["date"].to_period("M")
        rebalance = current_month != previous_month
        turnover = 0.0
        allocation_cost = 0.0
        if rebalance:
            turnover = 0.5 * (
                abs(target["core"] - weights["core"])
                + abs(target["satellite"] - weights["satellite"])
            )
            allocation_cost = portfolio_nav * turnover * cost_bps / 10000.0
            portfolio_nav -= allocation_cost
            total_cost += allocation_cost
            weights = dict(target)
        core_return = float(row["core_return"])
        satellite_return = float(row["satellite_return"])
        portfolio_return = (
            weights["core"] * core_return
            + weights["satellite"] * satellite_return
        )
        portfolio_nav *= 1.0 + portfolio_return
        gross_nav *= 1.0 + portfolio_return
        denominator = 1.0 + portfolio_return
        if denominator <= 0:
            raise ValueError("portfolio value became non-positive")
        core_close = weights["core"] * (1.0 + core_return) / denominator
        satellite_close = (
            weights["satellite"] * (1.0 + satellite_return) / denominator
        )
        records.append(
            {
                "trade_date": str(row["trade_date"]),
                "portfolio_nav": portfolio_nav,
                "gross_nav": gross_nav,
                "core_nav": float(row["nav_core"]) / float(frame["nav_core"].iloc[0]),
                "satellite_nav": float(row["nav_satellite"])
                / float(frame["nav_satellite"].iloc[0]),
                "benchmark_nav": float(row["benchmark_nav"]),
                "core_return": core_return,
                "satellite_return": satellite_return,
                "portfolio_return": portfolio_return,
                "core_weight_open": weights["core"],
                "satellite_weight_open": weights["satellite"],
                "core_weight_close": core_close,
                "satellite_weight_close": satellite_close,
                "allocation_turnover": turnover,
                "allocation_cost": allocation_cost,
                "rebalance": rebalance,
            }
        )
        weights = {"core": core_close, "satellite": satellite_close}
        previous_month = current_month
    daily = pd.DataFrame(records)
    years = max((len(daily) - 1) / 252.0, 1.0 / 252.0)
    return AllocationRun(
        daily=daily,
        annual_turnover=float(daily["allocation_turnover"].sum() / years),
        total_cost=total_cost,
    )


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    correlations: dict[str, float],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """按组合构建前冻结的分散门槛验收。"""
    full = metrics["full"]
    combined = full["combined"]
    core = full["core"]
    fold_combined = [metrics[name]["combined"] for name in FOLDS]
    drawdown_gap = abs(combined["max_drawdown"]) - abs(core["max_drawdown"])
    checks = {
        "history_audit": bool(audit["passed"]),
        "sleeve_correlation_at_most_075": abs(correlations["full"]) <= 0.75,
        "combined_return_at_least_core": (
            combined["annualized_return"] >= core["annualized_return"]
        ),
        "combined_sharpe_at_least_core": combined["sharpe"] >= core["sharpe"],
        "drawdown_worse_than_core_within_3pct": drawdown_gap <= 0.03,
        "combined_drawdown_within_25pct": combined["max_drawdown"] >= -0.25,
        "combined_positive_excess": combined["excess_return"] > 0,
        "all_folds_positive": all(
            item["annualized_return"] > 0 for item in fold_combined
        ),
        "allocation_turnover_below_1x": combined["annual_turnover"] <= 1.0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "drawdown_gap_vs_core": drawdown_gap,
        "return_lift_vs_core": (
            combined["annualized_return"] - core["annualized_return"]
        ),
        "sharpe_lift_vs_core": combined["sharpe"] - core["sharpe"],
    }


def build_decision_reason(gate: dict[str, Any]) -> str:
    """把冻结闸门的真实失败项写入研究历史。"""
    if gate["passed"]:
        return "70/30组合通过冻结门槛，仅允许进入组合级前向Paper"
    failed = [
        name
        for name, passed in gate["checks"].items()
        if not passed
    ]
    return f"70/30组合未通过冻结门槛（{', '.join(failed)}），归档且不注册"


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    daily: pd.DataFrame,
    annual: pd.DataFrame,
) -> None:
    """资产化组合净值、年度表现和失败/成功结论。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    daily_path = attempt.output_dir / "daily_nav.csv"
    annual_path = attempt.output_dir / "annual_metrics.csv"
    daily.to_csv(daily_path, index=False)
    annual.to_csv(annual_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=build_decision_reason(result["gate"]),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "组合研究报告"),
            ExperimentArtifact("daily_nav", daily_path, "组合及袖套每日净值"),
            ExperimentArtifact("annual_metrics", annual_path, "年度表现"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定监控事实库和两个策略声明版本。"""
    parts: list[str] = []
    for label, path in [
        ("monitoring", paths.monitoring_path),
        ("core_config", paths.config_dir / "strategies" / f"{CORE_ID}.json"),
        (
            "satellite_config",
            paths.config_dir / "strategies" / f"{SATELLITE_ID}.json",
        ),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
