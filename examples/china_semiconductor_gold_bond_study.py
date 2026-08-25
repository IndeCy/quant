"""半导体ETF、黄金和5年国债固定三等权多折研究。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples import a_share_tech_etf_rotation_study as execution_support
from examples import china_semiconductor_gold_bond_feasibility_study as feasibility
from examples import global_defensive_equal_study as global_core
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun
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


EXPERIMENT_ID = "china_semiconductor_gold_bond_equal_v1"
REPORT_PATH = Path("docs/research/china-semiconductor-gold-bond-equal-v1.md")
GOLD_BOND_ID = "semiconductor_study_gold_bond_equal_control"
SEMICONDUCTOR_ID = "semiconductor_direct_three_asset_control"
SP500_ID = "sp500_direct_semiconductor_three_asset_control"
GLOBAL_ID = "global_defensive_same_period_control"
STRESS_ID = "china_semiconductor_gold_bond_equal_20bps"
SEMICONDUCTOR = feasibility.SEMICONDUCTOR
GOLD = feasibility.GOLD
BOND = feasibility.BOND
SP500 = global_core.SP500_SYMBOL
BENCHMARK = global_core.BENCHMARK_SYMBOL
WEIGHTS = {SEMICONDUCTOR: 1 / 3, GOLD: 1 / 3, BOND: 1 / 3}
GOLD_BOND_WEIGHTS = {GOLD: 0.5, BOND: 0.5}
GLOBAL_WEIGHTS = dict(global_core.ASSET_WEIGHTS)
STUDY_START = feasibility.STUDY_START
LOCKED_START = "20240101"
FOLD_KEYS = ("2020_2021", "2022_2023", "2024_latest")
PERIODS = {
    "2020_2021": ("20200101", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
    "locked_test": (LOCKED_START, "LATEST"),
    "full": (STUDY_START, "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="半导体黄金国债固定三等权 V1",
    category="allocation_strategy",
    hypothesis=(
        "国内半导体成长与黄金、国债固定等权，能否显著降低半导体尾部并在不严重"
        "牺牲标普和全球防守机会成本的前提下形成低相关收益"
    ),
    definition={
        "feasibility_dependency": feasibility.EXPERIMENT_ID,
        "assets": {
            "china_growth": SEMICONDUCTOR,
            "real_asset": GOLD,
            "rate_asset": BOND,
            "weights": WEIGHTS,
        },
        "portfolio": {
            "rebalance": "monthly",
            "weight_grid": False,
            "timing": False,
            "leverage": 1.0,
        },
        "controls": {
            GOLD_BOND_ID: GOLD_BOND_WEIGHTS,
            SEMICONDUCTOR_ID: {SEMICONDUCTOR: 1.0},
            SP500_ID: {SP500: 1.0},
            GLOBAL_ID: GLOBAL_WEIGHTS,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
            "stamp_tax_rate": 0.0,
        },
        "gate": {
            "full_return_min": 0.09,
            "full_drawdown_floor": -0.24,
            "full_sharpe_min": 0.75,
            "full_calmar_min": 0.35,
            "return_lift_vs_gold_bond_min": 0.01,
            "drawdown_improvement_vs_semiconductor_min": 0.15,
            "sharpe_lift_vs_semiconductor_min": 0.10,
            "return_shortfall_vs_sp500_max": 0.03,
            "return_shortfall_vs_global_max": 0.02,
            "sharpe_shortfall_vs_global_max": 0.10,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.60,
            "locked_return_min": 0.09,
            "locked_drawdown_floor": -0.20,
            "locked_sharpe_min": 0.75,
            "positive_years_min": 5,
            "annual_turnover_max": 1.0,
            "stress_return_min": 0.08,
            "stress_sharpe_min": 0.70,
            "worst_day_floor": -0.08,
            "expected_shortfall_95_floor": -0.03,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "semiconductor_three_asset_multifold_v1",
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
        data_version=global_core._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_feasibility(paths)
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
    dict[str, dict[str, dict[str, float]]],
]:
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [SEMICONDUCTOR, GOLD, BOND, SP500, BENCHMARK],
        start_date=feasibility.LOAD_START,
        end_date=as_of_date,
    )
    audit = audit_panel(panel, as_of_date)
    if not audit["passed"]:
        raise ValueError(f"半导体三资产面板审计失败: {audit}")
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    controls = {
        GOLD_BOND_ID: GOLD_BOND_WEIGHTS,
        SEMICONDUCTOR_ID: {SEMICONDUCTOR: 1.0},
        SP500_ID: {SP500: 1.0},
        GLOBAL_ID: GLOBAL_WEIGHTS,
    }
    target_sets = {
        EXPERIMENT_ID: global_core._build_targets(signals, WEIGHTS),
        STRESS_ID: global_core._build_targets(signals, WEIGHTS),
        **{
            name: global_core._build_targets(signals, weights)
            for name, weights in controls.items()
        },
    }
    benchmark = global_core._benchmark_curve(panel)
    runs = {
        name: execution_support._run(
            name,
            targets,
            panel,
            benchmark,
            slippage_bps=20.0 if name == STRESS_ID else 5.0,
        )
        for name, targets in target_sets.items()
    }
    periods = {
        name: (start, panel.latest_common_date if end == "LATEST" else end)
        for name, (start, end) in PERIODS.items()
    }
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual_all = build_annual_metrics(runs, benchmark, panel.latest_common_date)
    annual = {
        year: item
        for year, item in annual_all[EXPERIMENT_ID].items()
        if year >= STUDY_START[:4]
    }
    diagnostics = build_diagnostics(paths, runs[EXPERIMENT_ID])
    gate = evaluate_gate(metrics, annual, diagnostics, audit)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "data_audit": audit,
        "period_metrics": metrics[EXPERIMENT_ID],
        "full_comparison": {
            name: values["full"]
            for name, values in metrics.items()
            if name != STRESS_ID
        },
        "annual_metrics": annual,
        "diagnostics": diagnostics,
        "latest_holdings": [
            {
                "symbol": symbol,
                "name": feasibility.NAMES[symbol],
                "target_weight": weight,
            }
            for symbol, weight in WEIGHTS.items()
        ],
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, target_sets


def audit_panel(panel, as_of_date: str) -> dict[str, Any]:
    expected = {SEMICONDUCTOR, GOLD, BOND, SP500, BENCHMARK}
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)
    ).days
    checks = {
        "all_assets_present": (
            {str(item["symbol"]) for item in panel.coverage} == expected
        ),
        "at_least_1600_common_days": len(panel.calendar) >= 1600,
        "fresh_within_five_days": 0 <= staleness <= 5,
        "no_duplicate_dates": not panel.adjusted_close.index.duplicated().any(),
        "all_prices_positive": bool(panel.adjusted_close.gt(0).all().all()),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "common_days": len(panel.calendar),
        "latest_common_date": panel.latest_common_date,
    }


def build_diagnostics(
    paths: RuntimePaths,
    run: RiskLayerRun,
) -> dict[str, float | int]:
    nav = run.result.daily_values.loc[STUDY_START:].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    drawdown = nav / nav.cummax() - 1.0
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift(fill_value=False)).cumsum()
    lengths = underwater.groupby(groups).sum()
    return {
        "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)),
        "worst_day": float(returns.min()),
        "expected_shortfall_95": float(
            returns[returns.le(threshold)].mean()
        ),
        "max_underwater_days": int(lengths.max()) if len(lengths) else 0,
        "quality_correlation": global_core.load_quality_correlation(paths, run),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, float]],
    diagnostics: dict[str, float | int],
    audit: dict[str, Any],
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    gold_bond = metrics[GOLD_BOND_ID]["full"]
    semiconductor = metrics[SEMICONDUCTOR_ID]["full"]
    sp500 = metrics[SP500_ID]["full"]
    global_equal = metrics[GLOBAL_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    checks = {
        "data_audit": bool(audit["passed"]),
        "full_return_at_least_9pct": full["annualized_return"] >= 0.09,
        "full_drawdown_within_24pct": full["max_drawdown"] >= -0.24,
        "full_sharpe_at_least_075": full["sharpe"] >= 0.75,
        "full_calmar_at_least_035": full["calmar"] >= 0.35,
        "return_lift_vs_gold_bond_at_least_1pct": (
            full["annualized_return"] - gold_bond["annualized_return"] >= 0.01
        ),
        "drawdown_improvement_vs_semiconductor_at_least_15pct": (
            full["max_drawdown"] - semiconductor["max_drawdown"] >= 0.15
        ),
        "sharpe_lift_vs_semiconductor_at_least_010": (
            full["sharpe"] - semiconductor["sharpe"] >= 0.10
        ),
        "return_shortfall_vs_sp500_within_3pct": (
            sp500["annualized_return"] - full["annualized_return"] <= 0.03
        ),
        "return_shortfall_vs_global_within_2pct": (
            global_equal["annualized_return"] - full["annualized_return"] <= 0.02
        ),
        "sharpe_shortfall_vs_global_within_010": (
            global_equal["sharpe"] - full["sharpe"] <= 0.10
        ),
        "all_three_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_25pct": (
            min(item["max_drawdown"] for item in folds) >= -0.25
        ),
        "median_fold_sharpe_at_least_060": (
            float(pd.Series([item["sharpe"] for item in folds]).median())
            >= 0.60
        ),
        "locked_return_at_least_9pct": locked["annualized_return"] >= 0.09,
        "locked_drawdown_within_20pct": locked["max_drawdown"] >= -0.20,
        "locked_sharpe_at_least_075": locked["sharpe"] >= 0.75,
        "at_least_five_positive_years": positive_years >= 5,
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "stress_return_at_least_8pct": stress["annualized_return"] >= 0.08,
        "stress_sharpe_at_least_070": stress["sharpe"] >= 0.70,
        "worst_day_within_8pct": float(diagnostics["worst_day"]) >= -0.08,
        "expected_shortfall_95_within_3pct": (
            float(diagnostics["expected_shortfall_95"]) >= -0.03
        ),
        "quality_correlation_at_most_050": (
            abs(float(diagnostics["quality_correlation"])) <= 0.50
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
    }


def require_feasibility(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        feasibility.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("半导体三资产数据门禁尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("半导体三资产数据门禁未通过")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, dict[str, float]]],
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav_comparison.csv"
    pd.DataFrame(
        {
            name: run.result.daily_values / float(run.result.daily_values.iloc[0])
            for name, run in runs.items()
        }
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    targets_path = attempt.output_dir / "monthly_targets.csv"
    pd.DataFrame(
        [
            {
                "strategy_id": name,
                "signal_date": date,
                "symbol": symbol,
                "target_weight": weight,
            }
            for name, strategy_targets in targets.items()
            for date, weights in strategy_targets.items()
            for symbol, weight in weights.items()
        ]
    ).to_csv(targets_path, index=False)
    diagnostics_path = attempt.output_dir / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(
            {
                "data_audit": result["data_audit"],
                "diagnostics": result["diagnostics"],
                "gate": result["gate"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    passed = bool(result["gate"]["passed"])
    failed = [
        name for name, value in result["gate"]["checks"].items() if not value
    ]
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "半导体黄金国债三等权通过冻结门槛，仅允许研究观察"
            if passed
            else f"半导体黄金国债失败（{', '.join(failed)}），不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "三资产研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("monthly_targets", targets_path, "月度目标"),
            ExperimentArtifact("diagnostics", diagnostics_path, "门槛诊断"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['annual_turnover']:.2f}x |"
        for name, item in result["period_metrics"].items()
    )
    comparisons = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for name, item in result["full_comparison"].items()
    )
    annual = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 半导体黄金国债固定三等权 V1

- 固定持有半导体ETF、黄金ETF、5年国债ETF，各三分之一。
- 月末恢复等权；无择时、无排名、无权重网格。
- M0 T+1、基础5bps、压力20bps；数据截止{result['latest_date']}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
{periods}

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{comparisons}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 尾部与独立性

- 年化波动：{result['diagnostics']['annualized_volatility']:.2%}
- 最差单日：{result['diagnostics']['worst_day']:.2%}
- 95% Expected Shortfall：{result['diagnostics']['expected_shortfall_95']:.2%}
- 最长水下期：{result['diagnostics']['max_underwater_days']}日
- 与Quality日收益相关性：{result['diagnostics']['quality_correlation']:.3f}

## 冻结门槛

{checks}

结论：{'通过冻结门槛，仅允许研究级观察' if result['gate']['passed'] else '未通过冻结门槛，归档且不注册'}。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260728")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
