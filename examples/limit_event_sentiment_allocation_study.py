"""涨跌停五日情绪驱动的A股/黄金/国债周频固定状态配置。"""

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
from examples import limit_event_sentiment_regime_feasibility_study as feasibility
from examples.cross_asset_dual_momentum_study import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
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


EXPERIMENT_ID = "limit_event_sentiment_defensive_allocation_v1"
STATIC_ID = "a_share_gold_bond_static_equal_control"
EQUITY_ID = "hs300_direct_sentiment_control"
STRESS_ID = "limit_event_sentiment_defensive_allocation_20bps"
REPORT_PATH = Path(
    "docs/research/limit-event-sentiment-defensive-allocation-v1.md"
)
EQUITY = "510300.SH"
GOLD = "518880.SH"
BOND = "511010.SH"
RISK_ON_WEIGHTS = {EQUITY: 0.60, GOLD: 0.20, BOND: 0.20}
RISK_OFF_WEIGHTS = {GOLD: 0.50, BOND: 0.50}
STATIC_WEIGHTS = {EQUITY: 1 / 3, GOLD: 1 / 3, BOND: 1 / 3}
SENTIMENT_THRESHOLD = 0.50
PERIODS = {
    "2023": ("20230101", "20231231"),
    "2024": ("20240101", "20241231"),
    "2025_latest": ("20250101", "LATEST"),
    "locked_test": ("20250101", "LATEST"),
    "full": (feasibility.STUDY_START, "LATEST"),
}
FOLDS = ("2023", "2024", "2025_latest")

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="涨跌停情绪防守配置 V1",
    category="market_regime_allocation",
    hypothesis=(
        "涨跌停家数五日情绪足够强时配置A股权益、否则转向黄金国债，是否能在不依赖"
        "个股选择的情况下改善沪深300和静态三资产的收益回撤比"
    ),
    definition={
        "dependency": feasibility.EXPERIMENT_ID,
        "period": [feasibility.STUDY_START, feasibility.RELIABLE_AS_OF],
        "state": {
            "indicator": "five_day_mean_signed_limit_event_ratio",
            "risk_on_if_greater_or_equal": SENTIMENT_THRESHOLD,
            "threshold_search": False,
        },
        "allocation": {
            "risk_on": RISK_ON_WEIGHTS,
            "risk_off": RISK_OFF_WEIGHTS,
            "signal": "weekly_last_trading_day_close",
            "execution": "next_trading_day_open",
        },
        "controls": {
            STATIC_ID: STATIC_WEIGHTS,
            EQUITY_ID: {EQUITY: 1.0},
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
            "stamp_tax_rate": 0.0,
        },
        "evaluation": {
            "periods": PERIODS,
            "full_return_min": 0.08,
            "full_drawdown_floor": -0.25,
            "full_sharpe_min": 0.70,
            "positive_excess_vs_hs300": True,
            "return_lift_vs_static_min": 0.005,
            "sharpe_lift_vs_static_min": 0.10,
            "positive_folds_min": 2,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.50,
            "locked_return_min": 0.08,
            "locked_drawdown_floor": -0.22,
            "locked_sharpe_min": 0.65,
            "annual_turnover_max": 15.0,
            "stress_return_min": 0.07,
            "stress_sharpe_min": 0.60,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_return_loading": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "limit_sentiment_allocation_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    normalized_as_of = min(
        str(as_of_date).replace("-", ""),
        feasibility.RELIABLE_AS_OF,
    )
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized_as_of,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_feasibility_passed(paths)
        result, runs, targets = calculate(paths, normalized_as_of)
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
    calendar_text = feasibility.load_calendar(paths.base_market_path, as_of_date)
    daily_sentiment = feasibility.load_daily_sentiment(
        paths.limit_list_increment_path,
        calendar_text,
        as_of_date,
    )
    signal_dates = feasibility.weekly_signal_dates(calendar_text)
    weekly = daily_sentiment[
        daily_sentiment["trade_date"].isin(signal_dates)
    ].copy()
    targets = build_sentiment_targets(weekly)
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [EQUITY, GOLD, BOND],
        start_date="20220101",
        end_date=as_of_date,
    )
    panel_signals = [
        date
        for date in targets
        if pd.Timestamp(date) in set(panel.calendar[:-1])
    ]
    targets = {date: targets[date] for date in panel_signals}
    static_targets = {
        date: dict(STATIC_WEIGHTS)
        for date in panel_signals
    }
    equity_targets = {date: {EQUITY: 1.0} for date in panel_signals}
    target_sets = {
        EXPERIMENT_ID: targets,
        STATIC_ID: static_targets,
        EQUITY_ID: equity_targets,
        STRESS_ID: targets,
    }
    benchmark = panel.adjusted_close[EQUITY].astype(float)
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
    periods = {
        name: (
            start,
            panel.latest_common_date if end == "LATEST" else end,
        )
        for name, (start, end) in PERIODS.items()
    }
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(
        runs[EXPERIMENT_ID],
        benchmark,
        panel.latest_common_date,
    )
    annual = {
        year: item
        for year, item in annual.items()
        if year >= feasibility.STUDY_START[:4]
    }
    quality_correlation = global_study.load_quality_correlation(
        paths,
        runs[EXPERIMENT_ID],
    )
    diagnostics = {
        "signal_weeks": len(targets),
        "risk_on_weeks": sum(
            weights.get(EQUITY, 0.0) > 0
            for weights in targets.values()
        ),
        "risk_on_share": sum(
            weights.get(EQUITY, 0.0) > 0
            for weights in targets.values()
        )
        / len(targets),
        "state_switches": count_state_switches(targets),
        "quality_correlation": quality_correlation,
    }
    gate = evaluate_gate(metrics, diagnostics)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "period_metrics": metrics[EXPERIMENT_ID],
        "full_comparison": {
            name: metrics[name]["full"]
            for name in [EXPERIMENT_ID, STATIC_ID, EQUITY_ID]
        },
        "annual_metrics": annual,
        "diagnostics": diagnostics,
        "gate": gate,
        "latest_holdings": [
            {
                "signal_date": max(targets),
                "symbol": symbol,
                "target_weight": weight,
            }
            for symbol, weight in targets[max(targets)].items()
        ],
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, targets


def build_sentiment_targets(
    weekly: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    targets = {}
    for row in weekly.itertuples(index=False):
        sentiment = float(row.sentiment_5d)
        targets[str(row.trade_date)] = dict(
            RISK_ON_WEIGHTS
            if sentiment >= SENTIMENT_THRESHOLD
            else RISK_OFF_WEIGHTS
        )
    return targets


def count_state_switches(targets: dict[str, dict[str, float]]) -> int:
    states = [
        weights.get(EQUITY, 0.0) > 0
        for _, weights in sorted(targets.items())
    ]
    return sum(left != right for left, right in zip(states, states[1:]))


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    static = metrics[STATIC_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[name] for name in FOLDS]
    checks = {
        "full_return_at_least_8pct": full["annualized_return"] >= 0.08,
        "full_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "full_sharpe_at_least_070": full["sharpe"] >= 0.70,
        "positive_excess_vs_hs300": full["excess_return"] > 0,
        "return_lift_vs_static_at_least_05pct": (
            full["annualized_return"] - static["annualized_return"] >= 0.005
        ),
        "sharpe_lift_vs_static_at_least_010": (
            full["sharpe"] - static["sharpe"] >= 0.10
        ),
        "at_least_two_positive_folds": sum(
            item["annualized_return"] > 0 for item in folds
        )
        >= 2,
        "worst_fold_drawdown_within_25pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.25,
        "median_fold_sharpe_at_least_050": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.50,
        "locked_return_at_least_8pct": locked["annualized_return"] >= 0.08,
        "locked_drawdown_within_22pct": locked["max_drawdown"] >= -0.22,
        "locked_sharpe_at_least_065": locked["sharpe"] >= 0.65,
        "annual_turnover_below_15x": full["annual_turnover"] <= 15.0,
        "stress_return_at_least_7pct": stress["annualized_return"] >= 0.07,
        "stress_sharpe_at_least_060": stress["sharpe"] >= 0.60,
        "quality_correlation_at_most_050": (
            abs(float(diagnostics["quality_correlation"])) <= 0.50
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def require_feasibility_passed(paths: RuntimePaths) -> None:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        feasibility.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("涨跌停五日情绪数据可行性实验尚未成功")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("涨跌停五日情绪数据门禁未通过")


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
    targets_path = attempt.output_dir / "weekly_targets.csv"
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
                "diagnostics": result["diagnostics"],
                "gate": result["gate"],
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
            "涨跌停情绪防守配置通过冻结门槛，仅允许继续研究"
            if passed
            else "涨跌停情绪防守配置未通过冻结门槛，归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "涨跌停情绪配置报告"),
            ExperimentArtifact("daily_nav", nav_path, "策略与对照净值"),
            ExperimentArtifact("weekly_targets", targets_path, "周频目标"),
            ExperimentArtifact("diagnostics", diagnostics_path, "状态诊断"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['annual_turnover']:.2f}x |"
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
    d = result["diagnostics"]
    return f"""# 涨跌停情绪防守配置 V1

- 情绪≥0.5：沪深300/黄金/国债 = 60/20/20；否则黄金/国债 = 50/50。
- 周末信号、T+1开盘、5bps；20bps压力；无阈值或权重搜索。
- 风险状态周占比：{d['risk_on_share']:.2%}；切换次数：{d['state_switches']}。
- 与 Quality 日收益相关性：{d['quality_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
{periods}

## 全期对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{comparison}

## 冻结门槛

{checks}

结论：{'通过研究门槛，但不进入生产' if result['gate']['passed'] else '未通过研究门槛，归档且不注册'}。
"""


def _data_version(paths: RuntimePaths) -> str:
    parts = []
    for label, path in [
        ("limit_cache", paths.limit_list_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
        ("monitoring", paths.monitoring_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=feasibility.RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
