"""Quality防守袖套Paper执行压力正交归因研究。"""

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
from examples.quality_defensive_assets_execution_attribution_report import (
    SCENARIO_NAMES,
    render_execution_attribution_report,
)
from examples.quality_defensive_assets_paper_actual_metrics import (
    actual_account_diagnostics,
)
from examples.quality_defensive_assets_paper_metrics import (
    paper_curve,
    paper_metric_summary,
)
from examples.quality_factor_study_support import slice_result
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


STRATEGY_ID = "quality_defensive_assets_execution_stress_attribution_v4"
REPORT_PATH = Path(
    "docs/research/quality-defensive-assets-execution-stress-attribution-v4.md"
)
SCENARIOS = {
    "baseline": {
        "execution_delay": 1,
        "slippage_bps": 10.0,
        "participation": 0.01,
    },
    "delay_only": {
        "execution_delay": 2,
        "slippage_bps": 10.0,
        "participation": 0.01,
    },
    "liquidity_only": {
        "execution_delay": 1,
        "slippage_bps": 10.0,
        "participation": 0.002,
    },
    "slippage_only": {
        "execution_delay": 1,
        "slippage_bps": 20.0,
        "participation": 0.01,
    },
    "combined_stress": {
        "execution_delay": 2,
        "slippage_bps": 20.0,
        "participation": 0.002,
    },
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防守袖套执行压力归因V4",
    category="paper_execution_attribution",
    hypothesis="组合压力下的持仓偏差主要来自延迟、流动性还是滑点",
    definition={
        "strategy": "quality_defensive_assets_core_scoped_70_15_15_v2",
        "capital": paper_study.INITIAL_CASH,
        "orthogonal_scenarios": SCENARIOS,
        "attribution_rule": {
            "position_driver": "largest_average_actual_position_gap",
            "return_driver": "largest_annual_return_loss_vs_baseline",
            "selection": "attribution_only_no_parameter_change",
        },
        "promotion_scope": "research_only",
        "methodology_version": "v4",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记正交场景指纹，再运行历史撮合。"""
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
        result, m0_run, paper_runs = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, m0_run, paper_runs)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], RiskLayerRun, dict[str, PaperTradingResult]]:
    """隔离执行延迟、成交参与率和滑点的单变量影响。"""
    (
        latest_date,
        benchmark,
        m0_run,
        targets,
        market_data,
    ) = paper_study.prepare_replay_inputs(paths, as_of_date)
    m0_result = slice_result(
        m0_run.result,
        "20150101",
        latest_date,
    )
    paper_runs = {
        scenario_id: paper_study._run_paper(
            targets,
            market_data,
            **config,
        )
        for scenario_id, config in SCENARIOS.items()
    }
    metrics = {
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
    attribution = identify_dominant_driver(metrics, diagnostics)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_execution_attribution_report(
            metrics,
            diagnostics,
            attribution,
            latest_date,
        ),
        encoding="utf-8",
    )
    return (
        {
            "strategy_id": STRATEGY_ID,
            "latest_date": latest_date,
            "paper_metrics": metrics,
            "diagnostics": diagnostics,
            "attribution": attribution,
            "promotion_allowed": False,
            "report_path": str(report_path),
            "reused": False,
        },
        m0_run,
        paper_runs,
    )


def identify_dominant_driver(
    metrics: dict[str, dict[str, float]],
    diagnostics: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """按预先声明的最大偏差规则归因，不选择策略参数。"""
    candidates = ("delay_only", "liquidity_only", "slippage_only")
    baseline_return = metrics["baseline"]["annualized_return"]
    gap_driver = max(
        candidates,
        key=lambda scenario_id: diagnostics[scenario_id][
            "average_actual_position_gap"
        ],
    )
    return_driver = max(
        candidates,
        key=lambda scenario_id: (
            baseline_return - metrics[scenario_id]["annualized_return"]
        ),
    )
    max_gap = diagnostics[gap_driver]["average_actual_position_gap"]
    max_loss = baseline_return - metrics[return_driver]["annualized_return"]
    same_driver = gap_driver == return_driver
    conclusion = (
        f"{SCENARIO_NAMES[gap_driver]}同时主导持仓与收益偏差"
        if same_driver
        else (
            f"{SCENARIO_NAMES[gap_driver]}主导持仓偏差，"
            f"{SCENARIO_NAMES[return_driver]}主导收益损失"
        )
    )
    return {
        "position_gap_driver": SCENARIO_NAMES[gap_driver],
        "return_loss_driver": SCENARIO_NAMES[return_driver],
        "position_gap_driver_id": gap_driver,
        "return_loss_driver_id": return_driver,
        "max_single_position_gap": float(max_gap),
        "max_single_annual_loss": float(max_loss),
        "conclusion": conclusion,
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    m0_run: RiskLayerRun,
    paper_runs: dict[str, PaperTradingResult],
) -> None:
    """归档正交场景净值和归因指标。"""
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
    metrics_path = attempt.output_dir / "execution_attribution.csv"
    pd.DataFrame(
        [
            {
                "scenario_id": scenario_id,
                **result["paper_metrics"][scenario_id],
                **result["diagnostics"][scenario_id],
            }
            for scenario_id in SCENARIOS
        ]
    ).to_csv(metrics_path, index=False)
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=str(result["attribution"]["conclusion"]),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "执行压力归因报告"),
            ExperimentArtifact("daily_nav", nav_path, "M0和正交场景净值"),
            ExperimentArtifact(
                "execution_attribution",
                metrics_path,
                "正交场景归因指标",
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
