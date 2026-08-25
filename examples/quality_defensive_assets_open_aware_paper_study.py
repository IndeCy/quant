"""Quality防守袖套的 T+1 开盘重算历史 Paper 研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.paper_execution import PaperTradingResult
from examples import quality_defensive_assets_paper_study as paper_study
from examples import quality_defensive_assets_study as base_study
from examples.quality_defensive_assets_paper_metrics import (
    incremental_execution_diagnostics,
    paper_curve,
    paper_metric_summary,
    position_value_drift_frame,
)
from examples.quality_factor_study_support import metric_summary, slice_result
from examples.quality_risk_layer_research import RiskLayerRun
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "quality_defensive_assets_open_aware_paper_v5"
LEGACY_ID = "paper_close_sized"
OPEN_AWARE_ID = "paper_t1_open_aware"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防守袖套T+1开盘重算Paper V5",
    category="paper_feasibility",
    hypothesis="开盘重算能否在不改变Alpha的前提下降低历史执行漂移",
    definition={
        "strategy": "quality_defensive_assets_frozen",
        "comparison": [
            "m0_execution",
            "paper_close_sized",
            "paper_t1_open_aware",
        ],
        "single_change": "target_quantity_sized_at_t1_open_with_slippage",
        "capital": paper_study.INITIAL_CASH,
        "execution": {
            "delay": 1,
            "slippage_bps": 10.0,
            "participation": 0.01,
            "commission_rate": 0.0003,
            "stamp_tax_rate": 0.001,
            "min_commission": 5.0,
            "lot_size": 100,
        },
        "fixed_gate": {
            "annual_return_gap_max": 0.02,
            "drawdown_gap_max": 0.03,
            "sharpe_gap_max": 0.10,
            "tracking_error_max": 0.02,
            "successful_orders_vs_m0_min": 0.98,
            "incremental_rejection_rate_max": 0.02,
            "average_post_execution_drift_max": 0.05,
            "latest_position_drift_max": 0.05,
        },
        "promotion_scope": "research_only",
        "methodology_version": "v5",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先锁定研究指纹，再读取大表并执行完整历史回放。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=base_study._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, m0_run, paper_runs, market_data = _calculate(
            paths,
            as_of_date,
        )
        _complete_attempt(
            attempt,
            result,
            m0_run,
            paper_runs,
            market_data,
        )
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    dict[str, Any],
    RiskLayerRun,
    dict[str, PaperTradingResult],
    pd.DataFrame,
]:
    """只改变定股数时点，其他策略和执行参数保持一致。"""
    (
        latest_date,
        benchmark,
        m0_run,
        targets,
        market_data,
    ) = paper_study.prepare_replay_inputs(paths, as_of_date)
    paper_runs = {
        LEGACY_ID: _run_policy(targets, market_data, open_aware=False),
        OPEN_AWARE_ID: _run_policy(targets, market_data, open_aware=True),
    }
    m0_result = slice_result(
        m0_run.result,
        "20150101",
        latest_date,
    )
    m0_metrics = metric_summary(m0_result, benchmark)
    m0_metrics["total_execution_cost"] = float(m0_result.total_cost)
    paper_metrics = {
        scenario_id: paper_metric_summary(
            scenario_id,
            paper_result,
            benchmark,
        )
        for scenario_id, paper_result in paper_runs.items()
    }
    diagnostics = {
        scenario_id: incremental_execution_diagnostics(
            paper_result,
            market_data,
            m0_result,
            paper_study.INITIAL_CASH,
        )
        for scenario_id, paper_result in paper_runs.items()
    }
    gate = evaluate_open_aware_gate(
        m0_metrics,
        paper_metrics[OPEN_AWARE_ID],
        diagnostics[OPEN_AWARE_ID],
    )
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "m0_metrics": m0_metrics,
        "paper_metrics": paper_metrics,
        "diagnostics": diagnostics,
        "gate": gate,
        "promotion_allowed": False,
        "paper_candidate": bool(gate["passed"]),
        "reused": False,
    }
    return result, m0_run, paper_runs, market_data


def _run_policy(
    targets: dict[str, dict[str, float]],
    market_data: pd.DataFrame,
    *,
    open_aware: bool,
) -> PaperTradingResult:
    """以相同券商参数运行指定定股数政策。"""
    return paper_study._run_paper(
        targets,
        market_data,
        execution_delay=1,
        slippage_bps=10.0,
        participation=0.01,
        open_aware_order_sizing=open_aware,
    )


def evaluate_open_aware_gate(
    m0_metrics: dict[str, float],
    paper_metrics: dict[str, float],
    diagnostics: dict[str, float],
) -> dict[str, Any]:
    """按研究开始前冻结的门槛判断是否值得长期观察。"""
    checks = {
        "annual_return_gap_within_2pct": (
            paper_metrics["annualized_return"]
            >= m0_metrics["annualized_return"] - 0.02
        ),
        "drawdown_gap_within_3pct": (
            paper_metrics["max_drawdown"]
            >= m0_metrics["max_drawdown"] - 0.03
        ),
        "sharpe_gap_within_010": (
            paper_metrics["sharpe"] >= m0_metrics["sharpe"] - 0.10
        ),
        "tracking_error_below_2pct": (
            diagnostics["tracking_error"] <= 0.02
        ),
        "successful_orders_at_least_98pct_of_m0": (
            diagnostics["successful_order_ratio_vs_m0"] >= 0.98
        ),
        "incremental_rejections_below_2pct": (
            diagnostics["incremental_rejection_rate_vs_m0"] <= 0.02
        ),
        "average_post_execution_drift_below_5pct": (
            diagnostics["average_post_execution_drift"] <= 0.05
        ),
        "latest_position_drift_below_5pct": (
            diagnostics["latest_position_drift"] <= 0.05
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    m0_run: RiskLayerRun,
    paper_runs: dict[str, PaperTradingResult],
    market_data: pd.DataFrame,
) -> None:
    """归档净值、执行诊断、漂移和可读结论。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(_render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    curves = {
        "m0": m0_run.result.daily_values,
        **{
            scenario_id: paper_curve(paper_result)
            for scenario_id, paper_result in paper_runs.items()
        },
    }
    pd.concat(
        [
            (curve / float(curve.iloc[0])).rename(name)
            for name, curve in curves.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    diagnostics_path = attempt.output_dir / "diagnostics.csv"
    pd.DataFrame(
        [
            {"scenario_id": scenario_id, **metrics}
            for scenario_id, metrics in result["diagnostics"].items()
        ]
    ).to_csv(diagnostics_path, index=False)
    drift_path = attempt.output_dir / "post_execution_drift.csv"
    pd.concat(
        [
            position_value_drift_frame(
                paper_result,
                market_data,
                allowed_dates={
                    order.execute_date for order in paper_result.orders
                },
            ).assign(scenario_id=scenario_id)
            for scenario_id, paper_result in paper_runs.items()
        ],
        ignore_index=True,
    ).to_csv(drift_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="CONTINUE_OBSERVATION" if passed else "REJECTED",
        decision_reason=(
            "T+1开盘重算通过冻结执行门槛，继续Paper观察"
            if passed
            else "T+1开盘重算未通过冻结执行门槛，不进入生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "开盘重算研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "三层历史净值"),
            ExperimentArtifact(
                "diagnostics",
                diagnostics_path,
                "执行偏差诊断",
            ),
            ExperimentArtifact(
                "post_execution_drift",
                drift_path,
                "成交日持仓漂移",
            ),
        ],
    )


def _render_report(result: dict[str, Any]) -> str:
    """渲染便于人工复核的核心指标对比。"""
    rows = []
    all_metrics = {
        "m0": result["m0_metrics"],
        **result["paper_metrics"],
    }
    for name, metrics in all_metrics.items():
        rows.append(
            "| {name} | {annual:.2%} | {drawdown:.2%} | {sharpe:.3f} |".format(
                name=name,
                annual=float(metrics["annualized_return"]),
                drawdown=float(metrics["max_drawdown"]),
                sharpe=float(metrics["sharpe"]),
            )
        )
    diagnostic_rows = [
        (
            "| {name} | {tracking:.2%} | {drift:.2%} | "
            "{latest:.2%} | {reject:.2%} |"
        ).format(
            name=name,
            tracking=float(metrics["tracking_error"]),
            drift=float(metrics["average_post_execution_drift"]),
            latest=float(metrics["latest_position_drift"]),
            reject=float(metrics["incremental_rejection_rate_vs_m0"]),
        )
        for name, metrics in result["diagnostics"].items()
    ]
    failed = [
        name
        for name, passed in result["gate"]["checks"].items()
        if not passed
    ]
    conclusion = (
        "通过，建议继续长期 Paper SLA 观察。"
        if result["gate"]["passed"]
        else f"未通过，失败门槛：{', '.join(failed)}。"
    )
    return "\n".join(
        [
            "# Quality 防守袖套 T+1 开盘重算历史研究",
            "",
            f"- 数据截止：{result['latest_date']}",
            "- 唯一变量：目标股数由 T 日收盘计算改为 T+1 开盘计算。",
            "",
            "## 收益风险",
            "",
            "| 口径 | 年化收益 | 最大回撤 | Sharpe |",
            "|---|---:|---:|---:|",
            *rows,
            "",
            "## 执行偏差",
            "",
            "| 口径 | 跟踪误差 | 成交后平均漂移 | 最新漂移 | 增量拒单率 |",
            "|---|---:|---:|---:|---:|",
            *diagnostic_rows,
            "",
            "## 结论",
            "",
            conclusion,
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(
        run_study(
            get_runtime_paths(),
            args.as_of_date,
            force=args.force,
        )
    )


if __name__ == "__main__":
    main()
