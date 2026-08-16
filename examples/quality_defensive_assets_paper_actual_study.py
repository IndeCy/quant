"""Quality防守袖套Paper实际账户相对M0账户差异研究。"""

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
from examples.quality_defensive_assets_paper_actual_metrics import (
    actual_account_diagnostics,
    actual_position_gap_frame,
    evaluate_actual_account_gate,
)
from examples.quality_defensive_assets_paper_actual_report import (
    render_actual_account_report,
)
from examples.quality_defensive_assets_paper_metrics import (
    paper_curve,
    paper_metric_summary,
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


STRATEGY_ID = "quality_defensive_assets_paper_actual_account_gap_v3"
REPORT_PATH = Path(
    "docs/research/quality-defensive-assets-paper-actual-account-gap-v3.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防守袖套Paper实际账户差异V3",
    category="paper_feasibility",
    hypothesis="Paper实际持仓相对M0实际持仓是否存在不可接受的新增偏差",
    definition={
        "strategy_and_execution": "identical_to_paper_feasibility_v1",
        "position_comparison": {
            "paper_side": "actual_holdings_after_broker_execution",
            "m0_side": "positions_reconstructed_from_actual_m0_trades",
            "valuation": "same_day_qfq_close",
            "denominator": "paper_total_account_value",
        },
        "gate": {
            "baseline_actual_position_gap_max": 0.05,
            "stress_actual_position_gap_max": 0.10,
            "baseline_latest_gap_max": 0.05,
            "stress_latest_gap_max": 0.10,
            "other_metrics": "identical_to_incremental_gap_v2",
        },
        "prior_result_policy": "preserve_v1_and_v2_rejected_records",
        "promotion_scope": "paper_candidate_only",
        "methodology_version": "v3",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记实际账户比较指纹后再读取并撮合历史数据。"""
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
    """运行相同M0和Paper，只改变持仓差异的比较基准。"""
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
        scenario_id: actual_account_diagnostics(
            paper_result,
            market_data,
            m0_result,
            paper_study.INITIAL_CASH,
        )
        for scenario_id, paper_result in paper_runs.items()
    }
    gate = evaluate_actual_account_gate(
        m0_metrics,
        paper_metrics,
        diagnostics,
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_actual_account_report(
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
    """归档实际账户净值和逐日持仓差异。"""
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
    m0_result = slice_result(
        m0_run.result,
        "20150101",
        str(result["latest_date"]),
    )
    gaps_path = attempt.output_dir / "actual_position_gaps.csv"
    pd.concat(
        [
            actual_position_gap_frame(
                paper_result,
                market_data,
                m0_result,
                allowed_dates={
                    order.execute_date for order in paper_result.orders
                },
            ).assign(scenario_id=scenario_id)
            for scenario_id, paper_result in paper_runs.items()
        ],
        ignore_index=True,
    ).to_csv(gaps_path, index=False)
    diagnostics_path = attempt.output_dir / "actual_account_diagnostics.csv"
    pd.DataFrame(
        [
            {"scenario_id": scenario_id, **metrics}
            for scenario_id, metrics in result["diagnostics"].items()
        ]
    ).to_csv(diagnostics_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "Paper实际账户相对M0账户偏差通过门槛"
            if passed
            else "Paper实际账户仍显著偏离M0账户"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "实际账户差异报告"),
            ExperimentArtifact("daily_nav", nav_path, "M0和Paper净值"),
            ExperimentArtifact(
                "actual_position_gaps",
                gaps_path,
                "实际账户逐日持仓差异",
            ),
            ExperimentArtifact(
                "actual_account_diagnostics",
                diagnostics_path,
                "实际账户增量指标",
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
