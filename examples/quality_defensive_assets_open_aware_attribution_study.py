"""Quality防守袖套 Open-aware Paper 失败门槛归因研究。"""

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


EXPERIMENT_ID = "quality_defensive_assets_open_aware_attribution_v6"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality防守袖套Open-aware失败归因V6",
    category="paper_execution_attribution",
    hypothesis="V5订单数失败是否主要由开盘重算消除无效小单而非真实漏单",
    definition={
        "source_policy": v5.STRATEGY_ID,
        "frozen_v5_gate_status": "REJECTED",
        "order_alignment_key": [
            "signal_date",
            "execute_date",
            "symbol",
        ],
        "categories": [
            "MATCHED_SAME_SIDE",
            "DIRECTION_CHANGED",
            "LEGACY_ONLY_MISSING_OPEN_BATCH",
            "LEGACY_ONLY_T1_DELTA_ZERO",
            "OPEN_AWARE_ONLY_NEW_DELTA",
        ],
        "tracking_attribution": {
            "basis": "daily_return_difference_vs_m0",
            "ranking": "squared_contribution",
            "top_dates": 20,
        },
        "diagnosis_rule": {
            "execution_defect": [
                "missing_open_batch_count_above_zero",
                "open_rejections_above_legacy",
            ],
            "count_metric_mismatch": [
                "generated_orders_lower",
                "t1_delta_zero_explains_gap",
                "rejections_not_higher",
            ],
        },
        "no_gate_change": True,
        "methodology_version": "v6",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """申请确定性研究指纹后再执行完整历史订单归因。"""
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
        result, artifacts = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, artifacts)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """运行冻结的旧政策和开盘重算政策并对齐订单。"""
    (
        latest_date,
        _benchmark,
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
    order_summary = summarize_order_alignment(
        alignment,
        paper_runs[v5.LEGACY_ID],
        paper_runs[v5.OPEN_AWARE_ID],
        m0_result,
    )
    tracking_summary = summarize_tracking(tracking)
    diagnosis = diagnose_gate_failure(order_summary, tracking_summary)
    result = {
        "experiment_id": EXPERIMENT_ID,
        "latest_date": latest_date,
        "order_attribution": order_summary,
        "tracking_attribution": tracking_summary,
        "diagnosis": diagnosis,
        "v5_gate_remains_rejected": True,
        "production_registration_allowed": False,
        "reused": False,
    }
    return result, {
        "order_alignment": alignment,
        "tracking_daily": tracking,
        "tracking_top20": top_tracking_dates(tracking),
    }


def diagnose_gate_failure(
    order_summary: dict[str, Any],
    tracking_summary: dict[str, float],
) -> dict[str, Any]:
    """按事前规则区分真实执行缺陷和订单计数口径错配。"""
    categories = order_summary["category_breakdown"]
    delta_zero = int(
        categories.get(
            "LEGACY_ONLY_T1_DELTA_ZERO",
            {},
        ).get("order_count", 0)
    )
    generated_gap = abs(
        min(int(order_summary["generated_order_gap_vs_legacy"]), 0)
    )
    missing_batches = int(order_summary["missing_open_batch_count"])
    rejected_change = int(order_summary["rejected_order_change"])
    count_gap_explained = delta_zero >= generated_gap
    execution_defect = missing_batches > 0 or rejected_change > 0
    count_metric_mismatch = (
        generated_gap > 0
        and count_gap_explained
        and rejected_change <= 0
        and not execution_defect
    )
    tracking_breach = (
        float(tracking_summary["tracking_error_annualized"]) > 0.02
    )
    return {
        "execution_defect_found": execution_defect,
        "count_metric_mismatch_supported": count_metric_mismatch,
        "generated_order_gap": generated_gap,
        "legacy_only_delta_zero_orders": delta_zero,
        "count_gap_fully_explained": count_gap_explained,
        "tracking_error_still_above_v5_gate": tracking_breach,
        "recommended_action": (
            "FIX_EXECUTION_LOGIC"
            if execution_defect
            else "KEEP_V5_REJECTED_AND_REVIEW_GATE_SEMANTICS"
        ),
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    frames: dict[str, pd.DataFrame],
) -> None:
    """归档逐单和逐日证据，不覆盖V5历史结果。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(_render_report(result), encoding="utf-8")
    artifacts = [
        ExperimentArtifact("summary", summary_path, "失败门槛归因报告")
    ]
    for name, frame in frames.items():
        path = attempt.output_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        artifacts.append(
            ExperimentArtifact(name, path, f"{name}归因明细")
        )
    diagnosis = result["diagnosis"]
    outcome = (
        "EXECUTION_DEFECT_FOUND"
        if diagnosis["execution_defect_found"]
        else "GATE_SEMANTICS_REVIEW"
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=outcome,
        decision_reason=str(diagnosis["recommended_action"]),
        artifacts=artifacts,
    )


def _render_report(result: dict[str, Any]) -> str:
    """输出可直接阅读的归因结论。"""
    orders = result["order_attribution"]
    tracking = result["tracking_attribution"]
    diagnosis = result["diagnosis"]
    rows = [
        "| {category} | {count} | {legacy:.2f}万 | {open_value:.2f}万 |".format(
            category=category,
            count=int(metrics["order_count"]),
            legacy=float(metrics["legacy_notional"]) / 10_000,
            open_value=float(metrics["open_aware_notional"]) / 10_000,
        )
        for category, metrics in sorted(
            orders["category_breakdown"].items()
        )
    ]
    return "\n".join(
        [
            "# Open-aware Paper V5 失败门槛归因",
            "",
            f"- 数据截止：{result['latest_date']}",
            "- V5 的 FAIL 记录保持不变，本报告只解释失败来源。",
            "",
            "## 订单差异",
            "",
            f"- M0 成功订单：{orders['m0_successful_orders']}",
            f"- 旧 Paper 成功订单：{orders['legacy_successful_orders']}",
            f"- Open-aware 成功订单：{orders['open_aware_successful_orders']}",
            f"- Open-aware 相比旧 Paper 少生成："
            f"{abs(min(orders['generated_order_gap_vs_legacy'], 0))} 单",
            f"- 拒单变化：{orders['rejected_order_change']}",
            f"- 缺开盘价批次：{orders['missing_open_batch_count']}",
            "",
            "| 分类 | 订单数 | 旧口径名义金额 | 新口径名义金额 |",
            "|---|---:|---:|---:|",
            *rows,
            "",
            "## 跟踪误差",
            "",
            f"- 年化跟踪误差："
            f"{tracking['tracking_error_annualized']:.2%}",
            f"- 前5个日期贡献："
            f"{tracking['top_5_dates_contribution']:.2%}",
            f"- 前10个日期贡献："
            f"{tracking['top_10_dates_contribution']:.2%}",
            f"- 成交日贡献："
            f"{tracking['execution_dates_contribution']:.2%}",
            "",
            "## 诊断",
            "",
            f"- 发现真实执行缺陷：{diagnosis['execution_defect_found']}",
            f"- 支持订单计数口径错配："
            f"{diagnosis['count_metric_mismatch_supported']}",
            f"- 少单是否被零差额订单解释："
            f"{diagnosis['count_gap_fully_explained']}",
            f"- 建议：{diagnosis['recommended_action']}",
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
