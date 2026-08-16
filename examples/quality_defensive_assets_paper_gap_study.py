"""Quality防守袖套Paper相对M0增量执行偏差研究。"""

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
from examples.quality_defensive_assets_paper_gap_report import (
    render_paper_gap_report,
)
from examples.quality_defensive_assets_paper_metrics import (
    evaluate_incremental_paper_gate,
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


STRATEGY_ID = "quality_defensive_assets_paper_incremental_gap_v2"
REPORT_PATH = Path(
    "docs/research/quality-defensive-assets-paper-incremental-gap-v2.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防守袖套Paper增量偏差V2",
    category="paper_feasibility",
    hypothesis="剔除M0共同拦截和预期T+1等待后，Paper是否仍有额外执行缺陷",
    definition={
        "strategy_and_execution": "identical_to_paper_feasibility_v1",
        "comparison_basis": {
            "rejections": "paper_rejections_minus_m0_rejections",
            "success_orders": "paper_successful_orders_divided_by_m0_trades",
            "position_drift": "measured_after_scheduled_execution_only",
            "tracking_error": "daily_return_difference_vs_m0",
        },
        "gate": {
            "baseline": {
                "annual_return_gap_max": 0.02,
                "drawdown_gap_max": 0.03,
                "sharpe_gap_max": 0.10,
                "tracking_error_max": 0.05,
                "successful_orders_vs_m0_min": 0.98,
                "incremental_rejection_rate_max": 0.02,
                "post_execution_drift_max": 0.05,
            },
            "stress": {
                "annual_return_min": 0.09,
                "drawdown_floor": -0.25,
                "sharpe_min": 0.60,
                "tracking_error_max": 0.08,
                "successful_orders_vs_m0_min": 0.95,
                "incremental_rejection_rate_max": 0.05,
                "post_execution_drift_max": 0.10,
            },
        },
        "v1_result_policy": "preserve_rejected_record",
        "promotion_scope": "paper_candidate_only",
        "methodology_version": "v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记新的比较口径，再复用相同策略与撮合输入。"""
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
        result, m0_run, paper_runs, market_data = _calculate(paths, as_of_date)
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
    """在相同撮合结果上计算相对M0的新增偏差。"""
    (
        latest_date,
        benchmark,
        m0_run,
        paper_runs,
        market_data,
    ) = paper_study.prepare_replay(paths, as_of_date)
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
    gate = evaluate_incremental_paper_gate(
        m0_metrics,
        paper_metrics,
        diagnostics,
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_paper_gap_report(
            m0_metrics,
            paper_metrics,
            diagnostics,
            gate,
            latest_date,
        ),
        encoding="utf-8",
    )
    return (
        {
            "strategy_id": STRATEGY_ID,
            "latest_date": latest_date,
            "m0_metrics": m0_metrics,
            "paper_metrics": paper_metrics,
            "diagnostics": diagnostics,
            "gate": gate,
            "promotion_allowed": False,
            "paper_candidate": bool(gate["passed"]),
            "report_path": str(report_path),
            "reused": False,
        },
        m0_run,
        paper_runs,
        market_data,
    )


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    m0_run: RiskLayerRun,
    paper_runs: dict[str, PaperTradingResult],
    market_data: pd.DataFrame,
) -> None:
    """归档独立V2结论，不覆盖V1失败记录。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    curves = {
        paper_study.M0_ID: m0_run.result.daily_values,
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
    diagnostics_path = attempt.output_dir / "incremental_diagnostics.csv"
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
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "相对M0增量执行偏差通过门槛，可创建长期Paper实例"
            if passed
            else "相对M0仍有不可接受执行偏差"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "Paper增量偏差报告"),
            ExperimentArtifact("daily_nav", nav_path, "M0和Paper净值"),
            ExperimentArtifact(
                "incremental_diagnostics",
                diagnostics_path,
                "相对M0增量偏差",
            ),
            ExperimentArtifact(
                "post_execution_drift",
                drift_path,
                "成交后逐日持仓漂移",
            ),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
