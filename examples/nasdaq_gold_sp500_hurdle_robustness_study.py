"""纳指100/黄金60/40相对场内标普500的冻结鲁棒性矩阵。"""

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

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import load_fund_portfolio_panel
from examples import global_defensive_equal_study as allocation
from examples import nasdaq_gold_sp500_hurdle_study as base
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
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


EXPERIMENT_ID = "nasdaq_gold_60_40_sp500_hurdle_robustness_v2"
REPORT_PATH = Path(
    "docs/research/nasdaq-gold-60-40-sp500-hurdle-robustness-v2.md"
)
BASELINE_ID = "baseline_60_40_monthly_5bps"
LOW_NASDAQ_ID = "nasdaq55_gold45_monthly_5bps"
HIGH_NASDAQ_ID = "nasdaq65_gold35_monthly_5bps"
QUARTERLY_ID = "nasdaq60_gold40_quarterly_5bps"
COST_ID = "nasdaq60_gold40_monthly_50bps"
T2_ID = "nasdaq60_gold40_monthly_t2_5bps"
SP500_ID = "sp500_direct_robustness_control"
SCENARIO_IDS = (
    BASELINE_ID,
    LOW_NASDAQ_ID,
    HIGH_NASDAQ_ID,
    QUARTERLY_ID,
    COST_ID,
    T2_ID,
)
NEIGHBORHOOD_WEIGHTS = {
    BASELINE_ID: dict(base.CANDIDATE_WEIGHTS),
    LOW_NASDAQ_ID: {base.NASDAQ: 0.55, base.GOLD: 0.45},
    HIGH_NASDAQ_ID: {base.NASDAQ: 0.65, base.GOLD: 0.35},
}
RETURN_LIFT_MIN = 0.005
SHARPE_LIFT_MIN = 0.05
VOLATILITY_GAP_MAX = 0.01
DRAWDOWN_GAP_MAX = 0.02

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="境内纳指100 × 黄金60/40相对标普500鲁棒性 V2",
    category="robustness",
    hypothesis=(
        "直接支配场内标普500的纳指黄金60/40结果，能否承受固定权重邻域、"
        "季度再平衡、50bps成本和T+2成交压力"
    ),
    definition={
        "source_experiment": base.EXPERIMENT_ID,
        "scenarios": {
            "weight_neighborhoods": NEIGHBORHOOD_WEIGHTS,
            QUARTERLY_ID: "60/40_calendar_quarter_end_months",
            COST_ID: "60/40_monthly_50bps",
            T2_ID: "60/40_monthly_one_extra_trading_day_delay",
        },
        "hard_opportunity_cost": {base.SP500: 1.0},
        "selection": "all_scenarios_frozen_before_read_no_best_selection",
        "evaluation": {
            "oos_start": base.OOS_START,
            "folds": base.FOLD_KEYS,
        },
        "frozen_gate": {
            "source_v2_gate": "pass",
            "all_scenarios_return_lift_vs_sp500_min": RETURN_LIFT_MIN,
            "all_scenarios_sharpe_lift_vs_sp500_min": SHARPE_LIFT_MIN,
            "all_scenarios_volatility_gap_vs_sp500_max": (
                VOLATILITY_GAP_MAX
            ),
            "all_scenarios_drawdown_gap_vs_sp500_max": DRAWDOWN_GAP_MAX,
            "all_scenarios_all_three_folds_positive": True,
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "fixed_sp500_opportunity_cost_matrix_v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记压力矩阵后再读取行情。"""
    normalized_as_of = min(
        str(as_of_date).replace("-", ""),
        base.RELIABLE_AS_OF,
    )
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized_as_of,
        data_version=base._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, runs = _calculate(paths, normalized_as_of)
        _complete_attempt(attempt, result, runs)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun]]:
    source = base.run_study(paths, as_of_date)
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [
            base.NASDAQ,
            base.GOLD,
            base.SP500,
            base.BOND,
            base.BENCHMARK,
        ],
        start_date=base.CALIBRATION_START,
        end_date=as_of_date,
    )
    audit = base.audit_panel(panel)
    if not audit["passed"]:
        raise ValueError(f"fund panel audit failed: {audit}")
    monthly = month_end_signal_dates(panel.calendar)
    quarterly = [
        date for date in monthly if pd.Timestamp(date).month in {3, 6, 9, 12}
    ]
    baseline_targets = allocation._build_targets(
        monthly,
        base.CANDIDATE_WEIGHTS,
    )
    target_sets = {
        scenario_id: allocation._build_targets(monthly, weights)
        for scenario_id, weights in NEIGHBORHOOD_WEIGHTS.items()
    }
    target_sets[QUARTERLY_ID] = allocation._build_targets(
        quarterly,
        base.CANDIDATE_WEIGHTS,
    )
    target_sets[COST_ID] = baseline_targets
    target_sets[T2_ID] = delay_targets_one_day(
        baseline_targets,
        panel.calendar,
    )
    target_sets[SP500_ID] = allocation._build_targets(
        monthly,
        {base.SP500: 1.0},
    )
    benchmark = allocation._benchmark_curve(panel)
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
                slippage_bps=50.0 if scenario_id == COST_ID else 5.0,
            ),
        )
        for scenario_id, targets in target_sets.items()
    }
    periods = {
        name: (start, panel.latest_common_date if end == "LATEST" else end)
        for name, (start, end) in base.PERIODS.items()
    }
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    volatilities = {
        scenario_id: annualized_volatility(
            run.result.daily_values.loc[base.OOS_START:]
        )
        for scenario_id, run in runs.items()
    }
    gate = evaluate_gate(
        metrics,
        volatilities,
        bool(source["gate"]["passed"]),
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "source_experiment": base.EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "data_audit": audit,
        "metrics": metrics,
        "volatilities": volatilities,
        "gate": gate,
        "decision": (
            "ROBUSTNESS_PASSED_RESEARCH_ONLY"
            if gate["passed"]
            else "ROBUSTNESS_FAILED_ARCHIVE_ONLY"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report_path = Path(result["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    return result, runs


def delay_targets_one_day(
    targets: dict[str, dict[str, float]],
    calendar: list[pd.Timestamp],
) -> dict[str, dict[str, float]]:
    """目标日再顺延一个交易日，使固定T+1执行引擎形成T+2成交。"""
    index = pd.DatetimeIndex(calendar)
    delayed: dict[str, dict[str, float]] = {}
    for date, weights in targets.items():
        position = int(index.searchsorted(pd.Timestamp(date), side="right"))
        if position < len(index):
            delayed[index[position].strftime("%Y%m%d")] = dict(weights)
    return delayed


def annualized_volatility(nav: pd.Series) -> float:
    returns = nav.astype(float).pct_change().dropna()
    return float(returns.std(ddof=1) * math.sqrt(252))


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    volatilities: dict[str, float],
    source_gate_passed: bool,
) -> dict[str, Any]:
    """所有冻结压力场景都必须继续支配场内标普500。"""
    sp500 = metrics[SP500_ID]["oos_full"]
    sp500_volatility = volatilities[SP500_ID]
    scenario = {
        scenario_id: metrics[scenario_id]["oos_full"]
        for scenario_id in SCENARIO_IDS
    }
    return_lifts = {
        key: item["annualized_return"] - sp500["annualized_return"]
        for key, item in scenario.items()
    }
    sharpe_lifts = {
        key: item["sharpe"] - sp500["sharpe"]
        for key, item in scenario.items()
    }
    volatility_gaps = {
        key: volatilities[key] - sp500_volatility for key in SCENARIO_IDS
    }
    drawdown_gaps = {
        key: (
            abs(item["max_drawdown"])
            - abs(sp500["max_drawdown"])
        )
        for key, item in scenario.items()
    }
    checks = {
        "source_v2_gate_passed": source_gate_passed,
        "all_scenarios_return_lift_vs_sp500_at_least_05pct": all(
            value >= RETURN_LIFT_MIN for value in return_lifts.values()
        ),
        "all_scenarios_sharpe_lift_vs_sp500_at_least_005": all(
            value >= SHARPE_LIFT_MIN for value in sharpe_lifts.values()
        ),
        "all_scenarios_volatility_gap_vs_sp500_within_1pct": all(
            value <= VOLATILITY_GAP_MAX
            for value in volatility_gaps.values()
        ),
        "all_scenarios_drawdown_gap_vs_sp500_within_2pct": all(
            value <= DRAWDOWN_GAP_MAX for value in drawdown_gaps.values()
        ),
        "all_scenarios_have_three_positive_folds": all(
            all(
                metrics[scenario_id][fold]["annualized_return"] > 0
                for fold in base.FOLD_KEYS
            )
            for scenario_id in SCENARIO_IDS
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "return_lifts_vs_sp500": return_lifts,
        "sharpe_lifts_vs_sp500": sharpe_lifts,
        "volatility_gaps_vs_sp500": volatility_gaps,
        "drawdown_gaps_vs_sp500": drawdown_gaps,
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
) -> None:
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "scenario_nav.csv"
    pd.DataFrame(
        {
            scenario_id: run.result.daily_values
            / float(run.result.daily_values.iloc[0])
            for scenario_id, run in runs.items()
        }
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    metrics_path = attempt.output_dir / "scenario_metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "data_audit": result["data_audit"],
                "metrics": result["metrics"],
                "volatilities": result["volatilities"],
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
            "全部冻结压力场景继续支配场内标普500，仅保留研究结论"
            if passed
            else "至少一个冻结压力场景不再支配场内标普500，归档"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "冻结鲁棒性报告"),
            ExperimentArtifact("scenario_nav", nav_path, "全部场景净值"),
            ExperimentArtifact(
                "scenario_metrics",
                metrics_path,
                "压力指标与逐项门槛",
            ),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    sp500 = result["metrics"][SP500_ID]["oos_full"]
    rows: list[str] = []
    for scenario_id in (*SCENARIO_IDS, SP500_ID):
        item = result["metrics"][scenario_id]["oos_full"]
        volatility = result["volatilities"][scenario_id]
        return_lift = (
            item["annualized_return"] - sp500["annualized_return"]
            if scenario_id != SP500_ID
            else 0.0
        )
        rows.append(
            f"| {scenario_id} | {item['annualized_return']:.2%} | "
            f"{return_lift:+.2%} | {item['max_drawdown']:.2%} | "
            f"{volatility:.2%} | {item['sharpe']:.3f} |"
        )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 境内纳指100 × 黄金60/40相对标普500鲁棒性 V2

- 数据截止：{result['latest_date']}
- 标的：159941.SZ、518880.SH；机会成本：513500.SH。
- 权重邻域、调仓频率、50bps成本和T+2场景均在读取结果前冻结。
- 使用场内ETF真实复权价格，QDII溢价/折价已包含在513500与159941价格中。

| 场景 | 年化收益 | 对标普提升 | 最大回撤 | 年化波动 | Sharpe |
|---|---:|---:|---:|---:|---:|
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
