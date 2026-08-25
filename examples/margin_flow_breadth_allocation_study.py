"""融资净买入广度驱动的A股/黄金/国债月频固定状态配置。"""

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
from examples import margin_flow_breadth_regime_feasibility_study as feasibility
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


EXPERIMENT_ID = "margin_flow_breadth_defensive_allocation_v1"
STATIC_ID = "margin_breadth_static_equal_control"
EQUITY_ID = "margin_breadth_hs300_direct_control"
STRESS_ID = "margin_flow_breadth_defensive_allocation_20bps"
REPORT_PATH = Path(
    "docs/research/margin-flow-breadth-defensive-allocation-v1.md"
)
EQUITY = "510300.SH"
GOLD = "518880.SH"
BOND = "511010.SH"
RISK_ON_WEIGHTS = {EQUITY: 0.60, GOLD: 0.20, BOND: 0.20}
RISK_OFF_WEIGHTS = {GOLD: 0.50, BOND: 0.50}
STATIC_WEIGHTS = {EQUITY: 1 / 3, GOLD: 1 / 3, BOND: 1 / 3}
BREADTH_THRESHOLD = 0.50
FOLDS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="融资广度防守配置 V1",
    category="market_regime_allocation",
    hypothesis=(
        "正融资净买入股票占有效两融股票过半时配置A股权益，否则转向黄金国债，是否能"
        "以低换手改善静态三资产的长期收益回撤比"
    ),
    definition={
        "dependency": feasibility.EXPERIMENT_ID,
        "state": {
            "indicator": "positive_margin_flow_count/valid_count",
            "risk_on_if_greater_or_equal": BREADTH_THRESHOLD,
            "threshold_search": False,
        },
        "allocation": {
            "risk_on": RISK_ON_WEIGHTS,
            "risk_off": RISK_OFF_WEIGHTS,
            "signal": "month_end_close_with_T_minus_1_visible_margin_data",
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
        "folds": FOLDS,
        "gate": {
            "full_return_min": 0.07,
            "full_drawdown_floor": -0.20,
            "full_sharpe_min": 0.90,
            "full_calmar_min": 0.35,
            "positive_excess_vs_hs300": True,
            "return_lift_vs_static_min": 0.005,
            "sharpe_lift_vs_static_min": 0.10,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.22,
            "median_fold_sharpe_min": 0.60,
            "locked_return_min": 0.08,
            "locked_drawdown_floor": -0.18,
            "locked_sharpe_min": 0.75,
            "annual_turnover_max": 3.0,
            "stress_return_min": 0.065,
            "stress_sharpe_min": 0.80,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_return_loading": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "margin_breadth_allocation_v1",
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
        require_feasibility_passed(paths)
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
    monthly = feasibility.load_source_monthly_artifact(paths)
    monthly["margin_breadth"] = (
        pd.to_numeric(monthly["positive_count"], errors="coerce")
        / pd.to_numeric(monthly["valid_count"], errors="coerce").replace(0, pd.NA)
    )
    monthly = monthly.dropna(subset=["margin_breadth"]).copy()
    targets = build_breadth_targets(monthly)
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [EQUITY, GOLD, BOND],
        start_date="20140101",
        end_date=as_of_date,
    )
    calendar_set = set(panel.calendar[:-1])
    targets = {
        date: weights
        for date, weights in targets.items()
        if pd.Timestamp(date) in calendar_set
    }
    static_targets = {date: dict(STATIC_WEIGHTS) for date in targets}
    equity_targets = {date: {EQUITY: 1.0} for date in targets}
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
    latest = panel.latest_common_date
    periods = {
        name: (start, latest if end == "LATEST" else end)
        for name, (start, end) in FOLDS.items()
    }
    periods["locked_test"] = ("20240101", latest)
    periods["full"] = ("20150101", latest)
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(runs[EXPERIMENT_ID], benchmark, latest)
    annual = {year: item for year, item in annual.items() if year >= "2015"}
    diagnostics = {
        "signal_months": len(targets),
        "risk_on_months": sum(
            weights.get(EQUITY, 0.0) > 0 for weights in targets.values()
        ),
        "risk_on_share": sum(
            weights.get(EQUITY, 0.0) > 0 for weights in targets.values()
        )
        / len(targets),
        "state_switches": count_state_switches(targets),
        "quality_correlation": global_study.load_quality_correlation(
            paths,
            runs[EXPERIMENT_ID],
        ),
    }
    gate = evaluate_gate(metrics, diagnostics)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": latest,
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


def build_breadth_targets(
    monthly: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    targets = {}
    for row in monthly.itertuples(index=False):
        breadth = float(row.margin_breadth)
        targets[str(row.signal_date)] = dict(
            RISK_ON_WEIGHTS
            if breadth >= BREADTH_THRESHOLD
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
        "full_return_at_least_7pct": full["annualized_return"] >= 0.07,
        "full_drawdown_within_20pct": full["max_drawdown"] >= -0.20,
        "full_sharpe_at_least_090": full["sharpe"] >= 0.90,
        "full_calmar_at_least_035": full["calmar"] >= 0.35,
        "positive_excess_vs_hs300": full["excess_return"] > 0,
        "return_lift_vs_static_at_least_05pct": (
            full["annualized_return"] - static["annualized_return"] >= 0.005
        ),
        "sharpe_lift_vs_static_at_least_010": (
            full["sharpe"] - static["sharpe"] >= 0.10
        ),
        "at_least_three_positive_folds": sum(
            item["annualized_return"] > 0 for item in folds
        )
        >= 3,
        "worst_fold_drawdown_within_22pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.22,
        "median_fold_sharpe_at_least_060": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.60,
        "locked_return_at_least_8pct": locked["annualized_return"] >= 0.08,
        "locked_drawdown_within_18pct": locked["max_drawdown"] >= -0.18,
        "locked_sharpe_at_least_075": locked["sharpe"] >= 0.75,
        "annual_turnover_below_3x": full["annual_turnover"] <= 3.0,
        "stress_return_at_least_65pct": stress["annualized_return"] >= 0.065,
        "stress_sharpe_at_least_080": stress["sharpe"] >= 0.80,
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
    if not latest or latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("融资广度数据门禁未通过")


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
            "融资广度防守配置通过冻结门槛，仅允许继续研究"
            if passed
            else "融资广度防守配置未通过冻结门槛，归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "融资广度配置报告"),
            ExperimentArtifact("daily_nav", nav_path, "策略与对照净值"),
            ExperimentArtifact("monthly_targets", targets_path, "月频目标"),
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
    return f"""# 融资净买入广度防守配置 V1

- 广度≥50%：沪深300/黄金/国债=60/20/20；否则黄金/国债=50/50。
- 月末T-1可见信号，T+1开盘，5bps；20bps压力；无参数搜索。
- 风险状态占比：{d['risk_on_share']:.2%}；切换：{d['state_switches']}次。
- 与Quality日收益相关性：{d['quality_correlation']:.3f}。

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
        ("system_state", paths.system_state_path),
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
