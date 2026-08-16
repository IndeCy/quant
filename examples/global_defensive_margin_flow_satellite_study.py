"""全球防守核心90%与已拒绝融资流卫星10%的固定组合研究。"""

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

from examples import global_defensive_mainline_satellite_study as portfolio_base
from examples import margin_flow_strategy_study as margin_base
from examples.quality_mainline_diversification_metrics import (
    build_annual_returns,
    build_period_correlations,
    build_period_metrics,
)
from examples.quality_mainline_diversification_study import (
    simulate_monthly_allocation,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "global_defensive_margin_flow_satellite_90_10_v1"
REPORT_PATH = Path(
    "docs/research/global-defensive-margin-flow-satellite-90-10-v1.md"
)
CORE_ID = "global_defensive_equal_v1"
SATELLITE_ID = margin_base.STRATEGY_ID
QUALITY_ID = "quality_balanced_value_v1"
CORE_WEIGHT = 0.90
SATELLITE_WEIGHT = 0.10
BASE_COST_BPS = 10.0
STRESS_COST_BPS = 50.0
FOLDS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球防守核心×融资流卫星90/10 V1",
    category="portfolio_strategy",
    hypothesis=(
        "融资净买入因子虽未通过单策略回撤和换手门槛，但在10%硬上限下是否能凭借不同"
        "经济来源提升全球防守核心收益，而不破坏组合回撤、Sharpe与Quality独立性"
    ),
    definition={
        "dependencies": {
            "core": CORE_ID,
            "satellite": SATELLITE_ID,
            "satellite_standalone_outcome_required": "REJECTED",
        },
        "sleeves": {
            "core": {"weight": CORE_WEIGHT},
            "satellite": {
                "weight": SATELLITE_WEIGHT,
                "hard_cap": SATELLITE_WEIGHT,
                "standalone_not_promoted": True,
            },
        },
        "source": {
            "core": "monitoring_strategy_nav_daily_net_cost",
            "satellite": "immutable_research_daily_nav_artifact_net_cost",
        },
        "allocation": {
            "weight_grid": False,
            "rebalance": "monthly_next_trading_day",
            "base_cost_bps": BASE_COST_BPS,
            "stress_cost_bps": STRESS_COST_BPS,
        },
        "folds": FOLDS,
        "gate": {
            "common_days_min": 2500,
            "sleeve_correlation_max": 0.35,
            "quality_correlation_max": 0.40,
            "full_return_min": 0.10,
            "full_drawdown_floor": -0.15,
            "full_sharpe_min": 1.10,
            "full_calmar_min": 0.65,
            "return_lift_vs_core_min": 0.002,
            "sharpe_shortfall_vs_core_max": 0.05,
            "drawdown_worse_vs_core_max": 0.02,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.17,
            "median_fold_sharpe_min": 0.75,
            "positive_years_min": 9,
            "allocation_turnover_max": 0.50,
            "stress_return_min": 0.095,
            "stress_drawdown_floor": -0.16,
            "stress_sharpe_min": 1.00,
        },
        "parameters_fixed_before_combined_return_loading": True,
        "promotion_scope": "portfolio_research_only_no_strategy_revival",
        "methodology_version": "rejected_satellite_hard_cap_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
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
        require_dependencies(paths)
        result, daily, annual = calculate(paths, as_of_date)
        complete_attempt(attempt, result, daily, annual)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    histories = load_core_and_quality(paths, as_of_date)
    satellite = load_margin_artifact(paths)
    common = histories[CORE_ID].merge(
        satellite[["trade_date", "strategy_nav"]],
        on="trade_date",
        how="inner",
        validate="one_to_one",
    ).rename(columns={"nav": "nav_core", "strategy_nav": "nav_satellite"})
    common = common.dropna(subset=["nav_core", "nav_satellite"]).copy()
    common["benchmark_nav"] = common["benchmark_nav"].astype(float)
    if len(common) < 2500:
        raise ValueError("90/10组合共同历史不足2500日")
    base_run = simulate_monthly_allocation(
        common,
        core_weight=CORE_WEIGHT,
        satellite_weight=SATELLITE_WEIGHT,
        cost_bps=BASE_COST_BPS,
    )
    stress_run = simulate_monthly_allocation(
        common,
        core_weight=CORE_WEIGHT,
        satellite_weight=SATELLITE_WEIGHT,
        cost_bps=STRESS_COST_BPS,
    )
    start_date = str(common["trade_date"].min())
    end_date = str(common["trade_date"].max())
    periods = {
        name: (start, end_date if end == "LATEST" else end)
        for name, (start, end) in FOLDS.items()
    }
    periods["full"] = (start_date, end_date)
    metrics = build_period_metrics(base_run.daily, periods)
    stress_metrics = build_period_metrics(stress_run.daily, periods)
    annual = build_annual_returns(base_run.daily)
    correlations = {
        "sleeve_full": build_period_correlations(
            base_run.daily,
            periods,
        )["full"],
        "quality_full": portfolio_base.calculate_reference_correlation(
            base_run.daily,
            histories[QUALITY_ID],
        ),
    }
    gate = evaluate_gate(
        metrics,
        stress_metrics,
        annual,
        correlations,
        common_days=len(common),
    )
    result = {
        "portfolio_id": EXPERIMENT_ID,
        "period": [start_date, end_date],
        "common_days": len(common),
        "period_metrics": metrics,
        "stress_full_metrics": stress_metrics["full"],
        "annual_metrics": annual.to_dict("records"),
        "correlations": correlations,
        "gate": gate,
        "decision": (
            "FORWARD_PORTFOLIO_PAPER_REQUIRED"
            if gate["passed"]
            else "REJECTED_NO_SATELLITE_REVIVAL"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, base_run.daily, annual


def load_core_and_quality(
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, pd.DataFrame]:
    histories = {}
    uri = f"file:{paths.monitoring_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        for strategy_id in [CORE_ID, QUALITY_ID]:
            histories[strategy_id] = pd.read_sql_query(
                """
                SELECT trade_date, nav, benchmark_nav
                FROM strategy_nav_daily
                WHERE strategy_id = ? AND trade_date <= ?
                ORDER BY trade_date
                """,
                connection,
                params=[strategy_id, as_of_date],
            )
    return histories


def load_margin_artifact(paths: RuntimePaths) -> pd.DataFrame:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        SATELLITE_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest:
        raise RuntimeError("融资流研究结果不存在")
    path = Path(str(latest["output_dir"])) / "daily_nav.csv"
    frame = pd.read_csv(path, dtype={"trade_date": str})
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "")
    return frame


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    stress_metrics: dict[str, dict[str, dict[str, float]]],
    annual: pd.DataFrame,
    correlations: dict[str, float],
    *,
    common_days: int,
) -> dict[str, Any]:
    combined = metrics["full"]["combined"]
    core = metrics["full"]["core"]
    stress = stress_metrics["full"]["combined"]
    folds = [metrics[name]["combined"] for name in FOLDS]
    checks = {
        "common_days_at_least_2500": common_days >= 2500,
        "sleeve_correlation_at_most_035": (
            abs(correlations["sleeve_full"]) <= 0.35
        ),
        "quality_correlation_at_most_040": (
            abs(correlations["quality_full"]) <= 0.40
        ),
        "full_return_at_least_10pct": combined["annualized_return"] >= 0.10,
        "full_drawdown_within_15pct": combined["max_drawdown"] >= -0.15,
        "full_sharpe_at_least_110": combined["sharpe"] >= 1.10,
        "full_calmar_at_least_065": combined["calmar"] >= 0.65,
        "return_lift_vs_core_at_least_02pct": (
            combined["annualized_return"] - core["annualized_return"] >= 0.002
        ),
        "sharpe_shortfall_vs_core_within_005": (
            combined["sharpe"] - core["sharpe"] >= -0.05
        ),
        "drawdown_worse_vs_core_within_2pct": (
            abs(combined["max_drawdown"]) - abs(core["max_drawdown"]) <= 0.02
        ),
        "all_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_17pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.17,
        "median_fold_sharpe_at_least_075": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.75,
        "at_least_nine_positive_years": int(
            annual["combined_return"].gt(0).sum()
        )
        >= 9,
        "allocation_turnover_below_05x": (
            combined["annual_turnover"] <= 0.50
        ),
        "stress_return_at_least_95pct": stress["annualized_return"] >= 0.095,
        "stress_drawdown_within_16pct": stress["max_drawdown"] >= -0.16,
        "stress_sharpe_at_least_100": stress["sharpe"] >= 1.00,
    }
    return {"passed": all(checks.values()), "checks": checks}


def require_dependencies(paths: RuntimePaths) -> None:
    repository = SystemRepository(paths.system_state_path)
    core = repository.load_experiment_detail(CORE_ID)
    margin = repository.load_experiment_detail(SATELLITE_ID)
    core_latest = core.get("latest_run") if core else None
    margin_latest = margin.get("latest_run") if margin else None
    if not core_latest or core_latest.get("outcome") != "PASSED_RESEARCH_GATE":
        raise RuntimeError("全球防守核心未通过研究门槛")
    if not margin_latest or margin_latest.get("outcome") != "REJECTED":
        raise RuntimeError("融资流卫星必须保持单策略REJECTED状态")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    daily: pd.DataFrame,
    annual: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    daily_path = attempt.output_dir / "daily_nav.csv"
    daily.to_csv(daily_path, index=False)
    annual_path = attempt.output_dir / "annual_metrics.csv"
    annual.to_csv(annual_path, index=False)
    diagnostics_path = attempt.output_dir / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(
            {
                "correlations": result["correlations"],
                "gate": result["gate"],
                "standalone_satellite_outcome": "REJECTED",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "90/10组合通过冻结门槛，仅允许组合级前向Paper；融资流单策略仍为REJECTED"
            if passed
            else "90/10组合未通过冻结门槛；融资流单策略保持REJECTED"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "90/10组合报告"),
            ExperimentArtifact("daily_nav", daily_path, "组合每日净值"),
            ExperimentArtifact("annual_metrics", annual_path, "年度表现"),
            ExperimentArtifact("diagnostics", diagnostics_path, "依赖与门槛"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {name} | {item['combined']['annualized_return']:.2%} | "
        f"{item['combined']['max_drawdown']:.2%} | "
        f"{item['combined']['sharpe']:.3f} | "
        f"{item['core']['annualized_return']:.2%} |"
        for name, item in result["period_metrics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    return f"""# 全球防守核心 × 融资流卫星 90/10 V1

- 共同区间：{result['period'][0]} 至 {result['period'][1]}，
  {result['common_days']} 个交易日。
- 融资流单策略结论保持 `REJECTED`；本研究只验证10%硬上限组合。
- 袖套/Quality相关：{result['correlations']['sleeve_full']:.3f} /
  {result['correlations']['quality_full']:.3f}。

| 区间 | 组合年化 | 组合回撤 | 组合Sharpe | 核心年化 |
|---|---:|---:|---:|---:|
{periods}

## 冻结门槛

{checks}

结论：`{result['decision']}`。不复活融资流单策略，不接入scheduler或生产订单。
"""


def _data_version(paths: RuntimePaths) -> str:
    monitoring = paths.monitoring_path.stat()
    margin = paths.margin_trade_path.stat()
    return (
        f"monitoring:{monitoring.st_size}:{monitoring.st_mtime_ns}|"
        f"margin:{margin.st_size}:{margin.st_mtime_ns}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260723")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
