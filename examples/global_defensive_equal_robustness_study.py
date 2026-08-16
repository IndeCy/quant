"""全球防守三资产等权的成本、延迟、频率和权重邻域审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import load_fund_portfolio_panel
from examples import global_defensive_equal_study as base
from examples.cross_asset_dual_momentum_study import FOLDS, STUDY_START
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.etf_momentum import month_end_signal_dates
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "global_defensive_equal_robustness_v1"
REPORT_PATH = Path("docs/research/global-defensive-equal-robustness-v1.md")
SCENARIO_WEIGHTS = {
    "baseline_monthly_5bps": dict(base.ASSET_WEIGHTS),
    "sp500_40_gold30_bond30": {
        base.SP500_SYMBOL: 0.40,
        base.GOLD_SYMBOL: 0.30,
        base.BOND_SYMBOL: 0.30,
    },
    "sp500_30_gold40_bond30": {
        base.SP500_SYMBOL: 0.30,
        base.GOLD_SYMBOL: 0.40,
        base.BOND_SYMBOL: 0.30,
    },
    "sp500_30_gold30_bond40": {
        base.SP500_SYMBOL: 0.30,
        base.GOLD_SYMBOL: 0.30,
        base.BOND_SYMBOL: 0.40,
    },
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球防守三资产等权鲁棒性 V1",
    category="robustness",
    hypothesis="固定三等权的低回撤收益是否能承受成本、T+2、季度调仓和10个百分点邻域扰动",
    definition={
        "source_strategy": base.STRATEGY_ID,
        "baseline": {
            "weights": base.ASSET_WEIGHTS,
            "rebalance": "monthly",
            "slippage_bps": 5.0,
            "execution_delay": 1,
        },
        "stress_scenarios": {
            "cost_20bps": "same_monthly_targets",
            "execution_t2": "same_targets_one_extra_trading_day_delay",
            "quarterly_rebalance": "calendar_quarter_end_months_only",
            "weight_neighborhoods": SCENARIO_WEIGHTS,
        },
        "selection": "no_scenario_selection_all_must_pass",
        "frozen_gate": {
            "baseline_research_gate": "all",
            "cost_20bps_return_min": 0.08,
            "cost_20bps_sharpe_min": 0.90,
            "quarterly_return_min": 0.08,
            "quarterly_drawdown_floor": -0.18,
            "quarterly_sharpe_min": 0.90,
            "t2_return_min": 0.08,
            "t2_drawdown_floor": -0.18,
            "t2_sharpe_min": 0.90,
            "all_neighborhood_return_min": 0.08,
            "all_neighborhood_drawdown_floor": -0.20,
            "all_neighborhood_sharpe_min": 0.90,
            "all_neighborhood_positive_folds_min": 3,
        },
        "promotion_scope": "forward_observation_only",
        "methodology_version": "fixed_robustness_matrix_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记完整压力矩阵后再读取基金大表。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=base._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, runs = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun]]:
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*base.ASSET_WEIGHTS, base.BENCHMARK_SYMBOL],
        start_date="20140101",
        end_date=as_of_date,
    )
    monthly = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    baseline_targets = base._build_targets(monthly, base.ASSET_WEIGHTS)
    quarterly = [
        date
        for date in monthly
        if date.month in {3, 6, 9, 12}
    ]
    target_sets = {
        scenario_id: base._build_targets(monthly, weights)
        for scenario_id, weights in SCENARIO_WEIGHTS.items()
    }
    target_sets["cost_20bps"] = baseline_targets
    target_sets["quarterly_5bps"] = base._build_targets(
        quarterly,
        base.ASSET_WEIGHTS,
    )
    target_sets["execution_t2_5bps"] = delay_targets_one_day(
        baseline_targets,
        panel.calendar,
    )
    benchmark = base._benchmark_curve(panel)
    runs = {
        scenario_id: run_risk_layer_backtest(
            scenario_id,
            "FIXED",
            targets,
            panel.bars,
            panel.calendar,
            benchmark,
            ExecutionModel(
                stamp_tax_rate=0.0,
                slippage_bps=20.0 if scenario_id == "cost_20bps" else 5.0,
            ),
        )
        for scenario_id, targets in target_sets.items()
    }
    periods = {
        key: (
            start,
            panel.latest_common_date if end == "LATEST" else end,
        )
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, panel.latest_common_date)
    metrics = build_period_metrics(
        {key: value.result for key, value in runs.items()},
        benchmark,
        periods,
    )
    baseline_gate = base.evaluate_gate(
        metrics["baseline_monthly_5bps"],
        base.build_annual_metrics(
            runs["baseline_monthly_5bps"],
            benchmark,
            panel.latest_common_date,
        ),
        base.load_quality_correlation(
            paths,
            runs["baseline_monthly_5bps"],
        ),
        base._asset_return_correlations(panel),
        _baseline_controls(paths, panel, monthly, benchmark),
    )
    gate = evaluate_gate(metrics, baseline_gate)
    result = {
        "strategy_id": base.STRATEGY_ID,
        "experiment_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "metrics": metrics,
        "baseline_gate": baseline_gate,
        "gate": gate,
        "decision": (
            "ROBUSTNESS_PASSED_CONTINUE_FORWARD_OBSERVATION"
            if gate["passed"]
            else "ROBUSTNESS_FAILED_REVIEW_OBSERVATION_ONLY"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    output = Path(result["report_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    return result, runs


def delay_targets_one_day(
    targets: dict[str, dict[str, float]],
    calendar: list[pd.Timestamp],
) -> dict[str, dict[str, float]]:
    """信号日顺延一个交易日，使固定T+1引擎形成T+2成交。"""
    index = pd.DatetimeIndex(calendar)
    delayed: dict[str, dict[str, float]] = {}
    for date, weights in targets.items():
        position = int(index.searchsorted(pd.Timestamp(date), side="right"))
        if position < len(index):
            delayed[index[position].strftime("%Y%m%d")] = dict(weights)
    return delayed


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    baseline_gate: dict[str, Any],
) -> dict[str, Any]:
    """所有压力场景必须通过，不从邻域中挑选最优者。"""
    cost = metrics["cost_20bps"]["full"]
    quarterly = metrics["quarterly_5bps"]["full"]
    delay = metrics["execution_t2_5bps"]["full"]
    neighborhoods = [
        scenario_id
        for scenario_id in SCENARIO_WEIGHTS
        if scenario_id != "baseline_monthly_5bps"
    ]
    checks = {
        "baseline_research_gate_passed": bool(baseline_gate["passed"]),
        "cost_20bps_return_at_least_8pct": (
            cost["annualized_return"] >= 0.08
        ),
        "cost_20bps_sharpe_at_least_090": cost["sharpe"] >= 0.90,
        "quarterly_return_at_least_8pct": (
            quarterly["annualized_return"] >= 0.08
        ),
        "quarterly_drawdown_within_18pct": (
            quarterly["max_drawdown"] >= -0.18
        ),
        "quarterly_sharpe_at_least_090": quarterly["sharpe"] >= 0.90,
        "t2_return_at_least_8pct": delay["annualized_return"] >= 0.08,
        "t2_drawdown_within_18pct": delay["max_drawdown"] >= -0.18,
        "t2_sharpe_at_least_090": delay["sharpe"] >= 0.90,
        "all_neighborhood_returns_at_least_8pct": all(
            metrics[item]["full"]["annualized_return"] >= 0.08
            for item in neighborhoods
        ),
        "all_neighborhood_drawdowns_within_20pct": all(
            metrics[item]["full"]["max_drawdown"] >= -0.20
            for item in neighborhoods
        ),
        "all_neighborhood_sharpes_at_least_090": all(
            metrics[item]["full"]["sharpe"] >= 0.90
            for item in neighborhoods
        ),
        "all_neighborhoods_have_three_positive_folds": all(
            sum(
                metrics[item][fold]["annualized_return"] > 0
                for fold in FOLDS
            )
            >= 3
            for item in neighborhoods
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _baseline_controls(
    paths: RuntimePaths,
    panel: Any,
    monthly: list[pd.Timestamp],
    benchmark: pd.Series,
) -> dict[str, dict[str, float]]:
    target_sets = {
        name: base._build_targets(monthly, weights)
        for name, weights in base.CONTROL_WEIGHTS.items()
    }
    target_sets[base.STRATEGY_ID] = base._build_targets(
        monthly,
        base.ASSET_WEIGHTS,
    )
    runs = {
        name: run_risk_layer_backtest(
            name,
            "FIXED",
            targets,
            panel.bars,
            panel.calendar,
            benchmark,
            ExecutionModel(stamp_tax_rate=0.0, slippage_bps=5.0),
        )
        for name, targets in target_sets.items()
    }
    metrics = build_period_metrics(
        {key: value.result for key, value in runs.items()},
        benchmark,
        {"full": (STUDY_START, panel.latest_common_date)},
    )
    return {key: value["full"] for key, value in metrics.items()}


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
) -> None:
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "scenario_nav.csv"
    pd.concat(
        [
            (run.result.daily_values / float(run.result.daily_values.iloc[0])).rename(
                scenario_id
            )
            for scenario_id, run in runs.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "全球防守三等权通过完整鲁棒性矩阵，继续前瞻观察"
            if passed
            else "全球防守三等权未通过完整鲁棒性矩阵，仅保留既有观察"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "鲁棒性报告"),
            ExperimentArtifact("scenario_nav", nav_path, "压力场景净值"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows: list[str] = []
    for scenario_id, periods in result["metrics"].items():
        full = periods["full"]
        rows.append(
            f"| {scenario_id} | {full['annualized_return']:.2%} | "
            f"{full['max_drawdown']:.2%} | {full['sharpe']:.3f} | "
            f"{full['annual_turnover']:.2f}x |"
        )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'}：{key}"
        for key, value in result["gate"]["checks"].items()
    )
    return f"""# 全球防守三资产等权鲁棒性 V1

- 数据截止：{result['latest_date']}
- 所有压力场景在读取行情前冻结，不做事后择优。

| 场景 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
{chr(10).join(rows)}

## 冻结门槛

{checks}

结论：{result['decision']}。
"""


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
