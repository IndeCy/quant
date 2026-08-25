"""全球防守核心与纳指黄金增长防守袖套各半的固定四资产研究。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import load_fund_portfolio_panel
from examples import global_defensive_equal_study as global_study
from examples import nasdaq_gold_sp500_hurdle_study as growth_study
from examples.cross_asset_dual_momentum_study import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.etf_momentum import month_end_signal_dates
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


EXPERIMENT_ID = "global_core_nasdaq_gold_four_asset_50_50_v1"
CORE_CONTROL_ID = "four_asset_global_defensive_control"
GROWTH_CONTROL_ID = "four_asset_nasdaq_gold_control"
SP500_CONTROL_ID = "four_asset_sp500_direct_control"
STRESS_ID = "global_core_nasdaq_gold_four_asset_20bps"
REPORT_PATH = Path(
    "docs/research/global-core-nasdaq-gold-four-asset-50-50-v1.md"
)
NASDAQ = "159941.SZ"
SP500 = "513500.SH"
GOLD = "518880.SH"
BOND = "511010.SH"
BENCHMARK = "510300.SH"
CORE_SLEEVE = {SP500: 1 / 3, GOLD: 1 / 3, BOND: 1 / 3}
GROWTH_SLEEVE = {NASDAQ: 0.60, GOLD: 0.40}
SLEEVE_WEIGHT = 0.50
ASSET_WEIGHTS = {
    NASDAQ: SLEEVE_WEIGHT * GROWTH_SLEEVE[NASDAQ],
    SP500: SLEEVE_WEIGHT * CORE_SLEEVE[SP500],
    GOLD: (
        SLEEVE_WEIGHT * CORE_SLEEVE[GOLD]
        + SLEEVE_WEIGHT * GROWTH_SLEEVE[GOLD]
    ),
    BOND: SLEEVE_WEIGHT * CORE_SLEEVE[BOND],
}
FOLDS = {
    "2016_2018": ("20160101", "20181231"),
    "2019_2021": ("20190101", "20211231"),
    "2022_2024": ("20220101", "20241231"),
    "2025_latest": ("20250101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球核心×纳指黄金四资产50/50 V1",
    category="allocation_strategy",
    hypothesis=(
        "全球防守三资产等权核心与高收益纳指黄金60/40袖套各占一半，是否能在保留"
        "跨资产低相关性的同时提高核心收益，并以更低回撤和更高Sharpe替代直接标普"
    ),
    definition={
        "dependencies": {
            "core": global_study.STRATEGY_ID,
            "growth_sleeve": growth_study.EXPERIMENT_ID,
            "growth_sleeve_standalone_outcome_required": "PASSED_RESEARCH_GATE",
        },
        "sleeves": {
            "global_defensive_equal": {
                "weight": SLEEVE_WEIGHT,
                "inside": CORE_SLEEVE,
            },
            "nasdaq_gold_60_40": {
                "weight": SLEEVE_WEIGHT,
                "inside": GROWTH_SLEEVE,
                "standalone_research_gate_passed": True,
            },
        },
        "resulting_asset_weights": ASSET_WEIGHTS,
        "portfolio": {
            "weight_grid": False,
            "rebalance": "monthly",
            "leverage": 1.0,
        },
        "controls": [
            "global_defensive_equal",
            "nasdaq_gold_60_40",
            "direct_sp500",
        ],
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
            "stamp_tax_rate": 0.0,
        },
        "folds": FOLDS,
        "gate": {
            "full_return_min": 0.13,
            "full_drawdown_floor": -0.20,
            "full_sharpe_min": 1.10,
            "full_calmar_min": 0.65,
            "return_lift_vs_sp500_min": 0.005,
            "sharpe_lift_vs_sp500_min": 0.15,
            "return_shortfall_vs_growth_max": 0.05,
            "drawdown_improvement_vs_growth_min": 0.03,
            "return_lift_vs_core_min": 0.03,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.22,
            "median_fold_sharpe_min": 0.80,
            "locked_return_min": 0.13,
            "locked_drawdown_floor": -0.20,
            "locked_sharpe_min": 0.90,
            "annual_turnover_max": 1.0,
            "stress_return_min": 0.125,
            "stress_drawdown_floor": -0.21,
            "stress_sharpe_min": 1.00,
            "quality_correlation_max": 0.35,
        },
        "parameters_fixed_before_combined_return_loading": True,
        "promotion_scope": "portfolio_research_only_no_auto_registration",
        "methodology_version": "two_sleeve_identity_weights_v1",
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
        result, runs, targets = calculate(paths, as_of_date)
        complete_attempt(attempt, result, runs, targets)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    dict[str, Any],
    dict[str, RiskLayerRun],
    dict[str, dict[str, float]],
]:
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [NASDAQ, SP500, GOLD, BOND, BENCHMARK],
        start_date="20140101",
        end_date=as_of_date,
    )
    start = panel.adjusted_close[[NASDAQ, SP500, GOLD, BOND]].dropna().index.min()
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= start
    ]
    targets = build_targets(signals, ASSET_WEIGHTS)
    target_sets = {
        EXPERIMENT_ID: targets,
        CORE_CONTROL_ID: build_targets(signals, CORE_SLEEVE),
        GROWTH_CONTROL_ID: build_targets(signals, GROWTH_SLEEVE),
        SP500_CONTROL_ID: build_targets(signals, {SP500: 1.0}),
        STRESS_ID: targets,
    }
    benchmark = panel.adjusted_close[BENCHMARK].astype(float)
    benchmark = benchmark / float(benchmark.iloc[0])
    runs = {
        name: run_risk_layer_backtest(
            name,
            "FIXED",
            strategy_targets,
            panel.bars,
            panel.calendar,
            benchmark,
            ExecutionModel(
                stamp_tax_rate=0.0,
                slippage_bps=20.0 if name == STRESS_ID else 5.0,
            ),
        )
        for name, strategy_targets in target_sets.items()
    }
    latest = panel.latest_common_date
    periods = {
        name: (start_date, latest if end == "LATEST" else end)
        for name, (start_date, end) in FOLDS.items()
    }
    periods["locked_test"] = ("20220101", latest)
    periods["full"] = (start.strftime("%Y%m%d"), latest)
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(runs[EXPERIMENT_ID], benchmark, latest)
    annual = {
        year: item
        for year, item in annual.items()
        if year >= start.strftime("%Y")
    }
    quality_correlation = global_study.load_quality_correlation(
        paths,
        runs[EXPERIMENT_ID],
    )
    gate = evaluate_gate(metrics, quality_correlation)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "period": [start.strftime("%Y%m%d"), latest],
        "asset_weights": ASSET_WEIGHTS,
        "period_metrics": metrics[EXPERIMENT_ID],
        "full_comparison": {
            name: metrics[name]["full"]
            for name in [
                EXPERIMENT_ID,
                CORE_CONTROL_ID,
                GROWTH_CONTROL_ID,
                SP500_CONTROL_ID,
            ]
        },
        "annual_metrics": annual,
        "quality_correlation": quality_correlation,
        "gate": gate,
        "latest_holdings": [
            {
                "signal_date": max(targets),
                "symbol": symbol,
                "target_weight": weight,
            }
            for symbol, weight in ASSET_WEIGHTS.items()
        ],
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, targets


def build_targets(
    signals: list[pd.Timestamp],
    weights: dict[str, float],
) -> dict[str, dict[str, float]]:
    return {
        date.strftime("%Y%m%d"): dict(weights)
        for date in signals
    }


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    quality_correlation: float,
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    core = metrics[CORE_CONTROL_ID]["full"]
    growth = metrics[GROWTH_CONTROL_ID]["full"]
    sp500 = metrics[SP500_CONTROL_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[name] for name in FOLDS]
    checks = {
        "full_return_at_least_13pct": full["annualized_return"] >= 0.13,
        "full_drawdown_within_20pct": full["max_drawdown"] >= -0.20,
        "full_sharpe_at_least_110": full["sharpe"] >= 1.10,
        "full_calmar_at_least_065": full["calmar"] >= 0.65,
        "return_lift_vs_sp500_at_least_05pct": (
            full["annualized_return"] - sp500["annualized_return"] >= 0.005
        ),
        "sharpe_lift_vs_sp500_at_least_015": (
            full["sharpe"] - sp500["sharpe"] >= 0.15
        ),
        "return_shortfall_vs_growth_within_5pct": (
            growth["annualized_return"] - full["annualized_return"] <= 0.05
        ),
        "drawdown_improvement_vs_growth_at_least_3pct": (
            abs(growth["max_drawdown"]) - abs(full["max_drawdown"]) >= 0.03
        ),
        "return_lift_vs_core_at_least_3pct": (
            full["annualized_return"] - core["annualized_return"] >= 0.03
        ),
        "all_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_22pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.22,
        "median_fold_sharpe_at_least_080": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.80,
        "locked_return_at_least_13pct": locked["annualized_return"] >= 0.13,
        "locked_drawdown_within_20pct": locked["max_drawdown"] >= -0.20,
        "locked_sharpe_at_least_090": locked["sharpe"] >= 0.90,
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "stress_return_at_least_125pct": stress["annualized_return"] >= 0.125,
        "stress_drawdown_within_21pct": stress["max_drawdown"] >= -0.21,
        "stress_sharpe_at_least_100": stress["sharpe"] >= 1.00,
        "quality_correlation_at_most_035": abs(quality_correlation) <= 0.35,
    }
    return {"passed": all(checks.values()), "checks": checks}


def require_dependencies(paths: RuntimePaths) -> None:
    repository = SystemRepository(paths.system_state_path)
    core = repository.load_experiment_detail(global_study.STRATEGY_ID)
    growth = repository.load_experiment_detail(growth_study.EXPERIMENT_ID)
    core_latest = core.get("latest_run") if core else None
    growth_latest = growth.get("latest_run") if growth else None
    if not core_latest or core_latest.get("outcome") != "PASSED_RESEARCH_GATE":
        raise RuntimeError("全球防守核心未通过研究门槛")
    if (
        not growth_latest
        or growth_latest.get("outcome") != "PASSED_RESEARCH_GATE"
    ):
        raise RuntimeError("纳指黄金V3袖套未通过研究门槛")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, float]],
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame(
        {
            name: run.result.daily_values
            / float(run.result.daily_values.iloc[0])
            for name, run in runs.items()
        }
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    targets_path = attempt.output_dir / "monthly_targets.csv"
    pd.DataFrame(
        [
            {
                "signal_date": date,
                "symbol": symbol,
                "target_weight": weight,
            }
            for date, weights in targets.items()
            for symbol, weight in weights.items()
        ]
    ).to_csv(targets_path, index=False)
    diagnostics_path = attempt.output_dir / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(
            {
                "asset_weights": result["asset_weights"],
                "quality_correlation": result["quality_correlation"],
                "gate": result["gate"],
                "growth_sleeve_standalone_outcome": "PASSED_RESEARCH_GATE",
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
            "四资产50/50袖套组合通过冻结门槛，仅允许组合级前向Paper"
            if passed
            else "四资产50/50袖套组合未通过冻结门槛，底层袖套结论不变"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "四资产组合报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("monthly_targets", targets_path, "月频目标"),
            ExperimentArtifact("diagnostics", diagnostics_path, "依赖与门槛"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for name, item in result["period_metrics"].items()
    )
    comparison = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for name, item in result["full_comparison"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    weights = " / ".join(
        f"{symbol} {weight:.1%}"
        for symbol, weight in result["asset_weights"].items()
    )
    return f"""# 全球核心 × 纳指黄金四资产50/50 V1

- 资产权重：{weights}
- 月频恢复固定权重，T+1开盘，5bps；20bps压力；无权重网格。
- 纳指黄金 V3 袖套已通过研究门槛；本研究只判断两袖套组合层。
- 与Quality日收益相关性：{result['quality_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{periods}

## 全期对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{comparison}

## 冻结门槛

{checks}

结论：{'通过研究门槛，但不进入生产' if result['gate']['passed'] else '未通过研究门槛，归档且不改变底层袖套'}。
"""


def _data_version(paths: RuntimePaths) -> str:
    parts = []
    for label, path in [
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
        ("monitoring", paths.monitoring_path),
        ("system_state", paths.system_state_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260615")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
