"""纳指、标普、黄金、国债周频20日相对动量Top2研究。"""

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
from examples import global_defensive_equal_study as global_study
from examples import global_four_asset_weekly_momentum_feasibility_study as feasibility
from examples import global_core_nasdaq_gold_four_asset_study as four_asset
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun
from factors.etf_relative_strength import weekly_signal_dates
from factors.etf_weekly_relative_momentum import (
    build_top_momentum_targets,
    calculate_weekly_relative_momentum,
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


EXPERIMENT_ID = "global_four_asset_weekly_20d_momentum_top2_v1"
REPORT_PATH = Path(
    "docs/research/global-four-asset-weekly-20d-momentum-top2-v1.md"
)
STRESS_ID = "global_four_asset_weekly_20d_momentum_top2_20bps"
EQUAL_CONTROL_ID = "global_four_asset_static_equal_control"
GROWTH_CONTROL_ID = "nasdaq_gold_60_40_weekly_momentum_control"
SP500_CONTROL_ID = "sp500_direct_weekly_momentum_control"
SYMBOLS = feasibility.SYMBOLS
NAMES = feasibility.NAMES
LOOKBACK_DAYS = feasibility.LOOKBACK_DAYS
TOP_N = feasibility.TOP_N
STUDY_START = feasibility.STUDY_START
LOCKED_START = "20220101"
FOLD_KEYS = ("2016_2018", "2019_2021", "2022_2024", "2025_latest")
PERIODS = {
    "2016_2018": ("20160101", "20181231"),
    "2019_2021": ("20190101", "20211231"),
    "2022_2024": ("20220101", "20241231"),
    "2025_latest": ("20250101", "LATEST"),
    "locked_test": (LOCKED_START, "LATEST"),
    "full": (STUDY_START, "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球四资产周频20日动量Top2 V1",
    category="allocation_strategy",
    hypothesis=(
        "纳指、标普、黄金和国债中周频持有20日收益最强两类，能否用更快主线切换"
        "战胜静态四等权、标普和纳指黄金60/40"
    ),
    definition={
        "feasibility_dependency": feasibility.EXPERIMENT_ID,
        "universe": NAMES,
        "signal": {
            "formula": "close_t/close_t_minus_20-1",
            "ranking": "descending",
            "signal_time": "weekly_last_trading_day_close",
            "absolute_filter": None,
        },
        "portfolio": {
            "top_n": TOP_N,
            "weighting": "equal_50_50",
            "rebalance": "weekly",
            "cash": 0.0,
            "parameter_grid": False,
        },
        "controls": {
            EQUAL_CONTROL_ID: "same_four_assets_static_equal",
            GROWTH_CONTROL_ID: {
                four_asset.NASDAQ: 0.60,
                four_asset.GOLD: 0.40,
            },
            SP500_CONTROL_ID: {four_asset.SP500: 1.0},
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
            "full_return_min": 0.12,
            "full_drawdown_floor": -0.25,
            "full_sharpe_min": 0.90,
            "full_calmar_min": 0.45,
            "return_lift_vs_equal_min": 0.01,
            "sharpe_lift_vs_equal_min": 0.05,
            "return_lift_vs_sp500_min": 0.005,
            "sharpe_lift_vs_sp500_min": 0.10,
            "drawdown_improvement_vs_sp500_min": 0.05,
            "return_shortfall_vs_growth_max": 0.04,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.30,
            "median_fold_sharpe_min": 0.70,
            "locked_return_min": 0.12,
            "locked_drawdown_floor": -0.25,
            "locked_sharpe_min": 0.85,
            "positive_years_min": 8,
            "annual_turnover_max": 12.0,
            "stress_return_min": 0.11,
            "stress_sharpe_min": 0.80,
            "worst_day_floor": -0.08,
            "expected_shortfall_95_floor": -0.03,
            "quality_correlation_max": 0.50,
            "selection_share_range": [0.10, 0.40],
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "weekly_global_momentum_multifold_v1",
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
        data_version=four_asset._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_feasibility(paths)
        result, runs, targets, states, holdings = calculate(paths, as_of_date)
        complete_attempt(attempt, result, runs, targets, states, holdings)
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
    pd.DataFrame,
    pd.DataFrame,
]:
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*SYMBOLS, global_study.BENCHMARK_SYMBOL],
        start_date=feasibility.LOAD_START,
        end_date=as_of_date,
    )
    audit = audit_panel(panel, as_of_date)
    if not audit["passed"]:
        raise ValueError(f"全球四资产周频面板审计失败: {audit}")
    signals = [
        date
        for date in weekly_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    states = calculate_weekly_relative_momentum(
        panel.adjusted_close,
        signals,
        SYMBOLS,
        lookback_days=LOOKBACK_DAYS,
    )
    candidate_targets, holdings = build_top_momentum_targets(
        states,
        top_n=TOP_N,
    )
    control_weights = {
        EQUAL_CONTROL_ID: {symbol: 1.0 / len(SYMBOLS) for symbol in SYMBOLS},
        GROWTH_CONTROL_ID: {
            four_asset.NASDAQ: 0.60,
            four_asset.GOLD: 0.40,
        },
        SP500_CONTROL_ID: {four_asset.SP500: 1.0},
    }
    target_sets = {
        EXPERIMENT_ID: candidate_targets,
        STRESS_ID: candidate_targets,
        **{
            name: global_study._build_targets(signals, weights)
            for name, weights in control_weights.items()
        },
    }
    benchmark = global_study._benchmark_curve(panel)
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
    diagnostics = build_diagnostics(paths, runs[EXPERIMENT_ID], holdings)
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
        "latest_holdings": latest_holdings(holdings),
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, target_sets, states, holdings


def audit_panel(panel, as_of_date: str) -> dict[str, Any]:
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)
    ).days
    checks = {
        "all_assets_present": (
            {str(item["symbol"]) for item in panel.coverage}
            == {*SYMBOLS, global_study.BENCHMARK_SYMBOL}
        ),
        "at_least_2600_common_days": len(panel.calendar) >= 2600,
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
    holdings: pd.DataFrame,
) -> dict[str, Any]:
    nav = run.result.daily_values.loc[STUDY_START:].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    counts = holdings["symbol"].value_counts(normalize=True)
    selection = {
        symbol: float(counts.get(symbol, 0.0))
        for symbol in SYMBOLS
    }
    return {
        "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)),
        "worst_day": float(returns.min()),
        "expected_shortfall_95": float(
            returns[returns.le(threshold)].mean()
        ),
        "quality_correlation": global_study.load_quality_correlation(paths, run),
        "selection_share": selection,
    }


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, float]],
    diagnostics: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    equal = metrics[EQUAL_CONTROL_ID]["full"]
    growth = metrics[GROWTH_CONTROL_ID]["full"]
    sp500 = metrics[SP500_CONTROL_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    shares = list(diagnostics["selection_share"].values())
    checks = {
        "data_audit": bool(audit["passed"]),
        "full_return_at_least_12pct": full["annualized_return"] >= 0.12,
        "full_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "full_sharpe_at_least_090": full["sharpe"] >= 0.90,
        "full_calmar_at_least_045": full["calmar"] >= 0.45,
        "return_lift_vs_equal_at_least_1pct": (
            full["annualized_return"] - equal["annualized_return"] >= 0.01
        ),
        "sharpe_lift_vs_equal_at_least_005": (
            full["sharpe"] - equal["sharpe"] >= 0.05
        ),
        "return_lift_vs_sp500_at_least_05pct": (
            full["annualized_return"] - sp500["annualized_return"] >= 0.005
        ),
        "sharpe_lift_vs_sp500_at_least_010": (
            full["sharpe"] - sp500["sharpe"] >= 0.10
        ),
        "drawdown_improvement_vs_sp500_at_least_5pct": (
            full["max_drawdown"] - sp500["max_drawdown"] >= 0.05
        ),
        "return_shortfall_vs_growth_within_4pct": (
            growth["annualized_return"] - full["annualized_return"] <= 0.04
        ),
        "all_four_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_30pct": (
            min(item["max_drawdown"] for item in folds) >= -0.30
        ),
        "median_fold_sharpe_at_least_070": (
            float(pd.Series([item["sharpe"] for item in folds]).median())
            >= 0.70
        ),
        "locked_return_at_least_12pct": locked["annualized_return"] >= 0.12,
        "locked_drawdown_within_25pct": locked["max_drawdown"] >= -0.25,
        "locked_sharpe_at_least_085": locked["sharpe"] >= 0.85,
        "at_least_eight_positive_years": positive_years >= 8,
        "annual_turnover_below_12x": full["annual_turnover"] <= 12.0,
        "stress_return_at_least_11pct": stress["annualized_return"] >= 0.11,
        "stress_sharpe_at_least_080": stress["sharpe"] >= 0.80,
        "worst_day_within_8pct": diagnostics["worst_day"] >= -0.08,
        "expected_shortfall_95_within_3pct": (
            diagnostics["expected_shortfall_95"] >= -0.03
        ),
        "quality_correlation_at_most_050": (
            abs(diagnostics["quality_correlation"]) <= 0.50
        ),
        "selection_share_between_10_and_40pct": (
            bool(shares)
            and min(shares) >= 0.10
            and max(shares) <= 0.40
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
    }


def latest_holdings(holdings: pd.DataFrame) -> list[dict[str, Any]]:
    latest = str(holdings["signal_date"].max())
    rows = holdings[holdings["signal_date"].eq(latest)]
    return [
        {
            "symbol": str(row.symbol),
            "name": NAMES[str(row.symbol)],
            "target_weight": float(row.target_weight),
            "momentum": float(row.momentum),
        }
        for row in rows.sort_values("rank").itertuples(index=False)
    ]


def require_feasibility(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        feasibility.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("全球四资产周频动量数据门禁尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("全球四资产周频动量数据门禁未通过")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, dict[str, float]]],
    states: pd.DataFrame,
    holdings: pd.DataFrame,
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
    targets_path = attempt.output_dir / "weekly_targets.csv"
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
    states_path = attempt.output_dir / "weekly_states.csv"
    states.to_csv(states_path, index=False)
    holdings_path = attempt.output_dir / "weekly_holdings.csv"
    holdings.to_csv(holdings_path, index=False)
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
            "全球四资产周频20日动量通过冻结门槛，仅允许研究观察"
            if passed
            else f"全球四资产周频动量失败（{', '.join(failed)}），不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "周频动量报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("weekly_targets", targets_path, "周频目标"),
            ExperimentArtifact("weekly_states", states_path, "周频状态"),
            ExperimentArtifact("weekly_holdings", holdings_path, "周频持仓"),
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
    holdings = "\n".join(
        f"| {item['symbol']} | {item['name']} | "
        f"{item['target_weight']:.1%} | {item['momentum']:.2%} |"
        for item in result["latest_holdings"]
    )
    shares = "\n".join(
        f"| {symbol} | {NAMES[symbol]} | {share:.1%} |"
        for symbol, share in result["diagnostics"]["selection_share"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 全球四资产周频20日动量Top2 V1

- 固定资产：纳指、标普、黄金、5年国债。
- 每周最后交易日按过去20日收益从强到弱排名，Top2各50%。
- 下一交易日M0执行，基础5bps、压力20bps；不做窗口或Top-N网格。
- 数据共同截止：{result['latest_date']}。

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

## 最新目标

| 代码 | 资产 | 权重 | 20日收益 |
|---|---|---:|---:|
{holdings}

## 入选覆盖

| 代码 | 资产 | Top2入选占比 |
|---|---|---:|
{shares}

- 年化波动：{result['diagnostics']['annualized_volatility']:.2%}
- 最差单日：{result['diagnostics']['worst_day']:.2%}
- 95% Expected Shortfall：{result['diagnostics']['expected_shortfall_95']:.2%}
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
