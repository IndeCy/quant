"""Quality防守袖套 Open-aware 单票缺价重试历史验证。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.paper_execution import PaperTradingResult
from examples import quality_defensive_assets_open_aware_paper_study as v5
from examples import quality_defensive_assets_paper_study as paper_study
from examples import quality_defensive_assets_study as base_study
from examples.quality_defensive_assets_open_aware_attribution_metrics import (
    build_order_alignment,
    build_tracking_attribution,
    summarize_order_alignment,
    summarize_tracking,
    top_tracking_dates,
)
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


EXPERIMENT_ID = "quality_defensive_assets_open_aware_partial_retry_v9"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality防守袖套Open-aware部分重试V9",
    category="paper_feasibility",
    hypothesis="单票缺价冻结并次日重试能否消除整批跳过造成的执行偏差",
    definition={
        "strategy": "quality_defensive_assets_frozen",
        "baseline_policy": "t_signal_close_sized_t1_execution",
        "candidate_policy": {
            "sizing": "t1_open_with_slippage",
            "missing_open": (
                "freeze_unavailable_symbol_execute_tradable_symbols_"
                "retry_unresolved_symbols_only_next_trading_day"
            ),
            "supersede": "new_target_replaces_old_unresolved_target",
            "target_state": "full_target_replaces_stale_unfilled_symbols",
        },
        "execution": v5.RESEARCH_SPEC.definition["execution"],
        "fixed_gate": v5.RESEARCH_SPEC.definition["fixed_gate"],
        "comparison": ["m0", v5.LEGACY_ID, v5.OPEN_AWARE_ID],
        "no_alpha_change": True,
        "no_gate_change": True,
        "methodology_version": "v9",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记新执行语义指纹后运行完整历史验证。"""
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
        result, context = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, context)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, object]]:
    """用原冻结门槛比较M0、旧Paper和修复后的Open-aware。"""
    (
        latest_date,
        benchmark,
        m0_run,
        targets,
        market_data,
    ) = paper_study.prepare_replay_inputs(paths, as_of_date)
    paper_runs = {
        v5.LEGACY_ID: v5._run_policy(
            targets,
            market_data,
            open_aware=False,
        ),
        v5.OPEN_AWARE_ID: v5._run_policy(
            targets,
            market_data,
            open_aware=True,
        ),
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
    gate = v5.evaluate_open_aware_gate(
        m0_metrics,
        paper_metrics[v5.OPEN_AWARE_ID],
        diagnostics[v5.OPEN_AWARE_ID],
    )
    alignment = build_order_alignment(
        paper_runs[v5.LEGACY_ID],
        paper_runs[v5.OPEN_AWARE_ID],
        targets,
        market_data,
    )
    tracking = build_tracking_attribution(
        m0_result.daily_values,
        paper_runs[v5.LEGACY_ID],
        paper_runs[v5.OPEN_AWARE_ID],
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "latest_date": latest_date,
        "m0_metrics": m0_metrics,
        "paper_metrics": paper_metrics,
        "diagnostics": diagnostics,
        "gate": gate,
        "order_attribution": summarize_order_alignment(
            alignment,
            paper_runs[v5.LEGACY_ID],
            paper_runs[v5.OPEN_AWARE_ID],
            m0_result,
        ),
        "tracking_attribution": summarize_tracking(tracking),
        "production_registration_allowed": False,
        "long_term_paper_observation_allowed": bool(gate["passed"]),
        "reused": False,
    }
    return result, {
        "m0_run": m0_run,
        "paper_runs": paper_runs,
        "market_data": market_data,
        "alignment": alignment,
        "tracking": tracking,
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    context: dict[str, object],
) -> None:
    """归档V9净值、订单差异、漂移和跟踪误差证据。"""
    m0_run = context["m0_run"]
    paper_runs = context["paper_runs"]
    market_data = context["market_data"]
    if not isinstance(m0_run, RiskLayerRun):
        raise TypeError("m0_run type mismatch")
    if not isinstance(paper_runs, dict) or not isinstance(
        market_data,
        pd.DataFrame,
    ):
        raise TypeError("paper replay context type mismatch")
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(_render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    curves = {
        "m0": m0_run.result.daily_values,
        **{
            str(name): paper_curve(value)
            for name, value in paper_runs.items()
            if isinstance(value, PaperTradingResult)
        },
    }
    pd.concat(
        [
            (curve / float(curve.iloc[0])).rename(name)
            for name, curve in curves.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    artifacts = [
        ExperimentArtifact("summary", summary_path, "部分重试验证报告"),
        ExperimentArtifact("daily_nav", nav_path, "三层历史净值"),
    ]
    frames = {
        "order_alignment": context["alignment"],
        "tracking_daily": context["tracking"],
        "tracking_top20": top_tracking_dates(context["tracking"]),
        "post_execution_drift": pd.concat(
            [
                position_value_drift_frame(
                    value,
                    market_data,
                    allowed_dates={
                        order.execute_date for order in value.orders
                    },
                ).assign(scenario_id=str(name))
                for name, value in paper_runs.items()
                if isinstance(value, PaperTradingResult)
            ],
            ignore_index=True,
        ),
    }
    for name, frame in frames.items():
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{name} frame type mismatch")
        path = attempt.output_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        artifacts.append(ExperimentArtifact(name, path, name))
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="CONTINUE_OBSERVATION" if passed else "REJECTED",
        decision_reason=(
            "部分重试通过原冻结门槛，可继续长期Paper SLA"
            if passed
            else "部分重试仍未通过原冻结门槛"
        ),
        artifacts=artifacts,
    )


def _render_report(result: dict[str, Any]) -> str:
    """渲染V9核心结论。"""
    metrics = result["paper_metrics"][v5.OPEN_AWARE_ID]
    diagnostics = result["diagnostics"][v5.OPEN_AWARE_ID]
    orders = result["order_attribution"]
    failed = [
        name
        for name, passed in result["gate"]["checks"].items()
        if not passed
    ]
    return "\n".join(
        [
            "# Open-aware Paper 单票缺价部分重试 V9",
            "",
            f"- 数据截止：{result['latest_date']}",
            "- V5、V6、V7、V8历史结论保持不变。",
            "- 缺价股票冻结，其余股票执行，次日仅重试未完成股票。",
            "",
            "## 核心指标",
            "",
            f"- 年化收益：{metrics['annualized_return']:.2%}",
            f"- 最大回撤：{metrics['max_drawdown']:.2%}",
            f"- Sharpe：{metrics['sharpe']:.3f}",
            f"- 跟踪误差：{diagnostics['tracking_error']:.2%}",
            f"- 成交后平均漂移："
            f"{diagnostics['average_post_execution_drift']:.2%}",
            f"- 成功订单/M0："
            f"{diagnostics['successful_order_ratio_vs_m0']:.2%}",
            f"- 增量拒单率："
            f"{diagnostics['incremental_rejection_rate_vs_m0']:.2%}",
            f"- 缺开盘价批次：{orders['missing_open_batch_count']}",
            "",
            "## 冻结门槛",
            "",
            f"- 通过：{result['gate']['passed']}",
            f"- 失败项：{', '.join(failed) if failed else '无'}",
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
