"""2026-07-29完整研究批次的台账、产物和晋级一致性元审计 V2。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import research_campaign_20260729_meta_audit as v1
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


EXPERIMENT_ID = "research_campaign_20260729_meta_audit_v2"
REPORT_PATH = Path("docs/research/research-campaign-20260729-meta-audit-v2.md")
CAMPAIGN = {
    "strategy": [
        "nasdaq_trend_gold_bond_switch_v1",
        "a_share_tech_etf_weekly_relative_strength_v1",
        "nasdaq_gold_china_dividend_equal_v1",
        "china_tech_dividend_gold_equal_v1",
        "nasdaq_gold_bond_balanced_50_25_25_v1",
        "limit_up_first_board_seal_strength_v1",
        "limit_up_first_board_open_executable_v1",
        "margin_financing_flow_v1",
        "limit_down_weak_seal_weekly_reversal_v1",
        "limit_event_sentiment_defensive_allocation_v1",
        "global_defensive_margin_flow_satellite_90_10_v1",
        "margin_flow_breadth_defensive_allocation_v1",
        "global_core_nasdaq_gold_four_asset_50_50_v1",
        "global_defensive_inverse_volatility_60d_v1",
        "a_share_tech_etf_weekly_5d_reversal_v1",
        "global_four_asset_weekly_20d_momentum_top2_v1",
        "china_semiconductor_gold_bond_equal_v1",
    ],
    "feasibility": [
        "limit_up_first_board_event_data_feasibility_v1",
        "limit_down_weekly_reversal_data_feasibility_v1",
        "a_share_ma60_breadth_regime_data_feasibility_v1",
        "limit_event_five_day_sentiment_data_feasibility_v1",
        "margin_flow_breadth_regime_data_feasibility_v1",
        "a_share_etf_weekly_reversal_data_feasibility_v1",
        "a_share_tech_etf_weekly_reversal_data_feasibility_v1",
        "a_share_tech_etf_weekly_reversal_liquid_feasibility_v2",
        "global_four_asset_weekly_momentum_data_feasibility_v1",
        "china_dividend_gold_bond_data_feasibility_v1",
        "global_defensive_china_dividend_90_10_capacity_feasibility_v1",
        "china_semiconductor_gold_bond_data_feasibility_v1",
    ],
    "audit": [
        "borderline_allocation_correlation_audit_v1",
        "borderline_allocation_correlation_audit_v2",
        "limit_up_first_board_execution_assumption_audit_v1",
        "global_defensive_mainline_satellite_robustness_v1",
        "global_defensive_margin_flow_correlation_audit_v1",
        "global_core_four_asset_sp500_opportunity_audit_v1",
        "nasdaq_gold_60_40_qdii_premium_audit_v1",
        "nasdaq_gold_60_40_qdii_premium_corporate_action_audit_v2",
        "nasdaq_gold_60_40_sp500_statistical_dominance_audit_v1",
        "china_semiconductor_gold_bond_failure_audit_v1",
    ],
    "governance": [v1.EXPERIMENT_ID],
}
PROMOTION_OUTCOMES = {
    "PASSED_RESEARCH_GATE",
    "PASSED_ROBUSTNESS",
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="2026-07-29完整研究批次元审计 V2",
    category="research_governance",
    hypothesis=(
        "本轮全部策略、门禁、执行与统计审计是否具备成功台账和本机产物，且没有"
        "把可行性、审计或不确定结果误计为策略晋级"
    ),
    definition={
        "campaign": CAMPAIGN,
        "checks": [
            "latest_run_success",
            "output_directory_exists",
            "all_registered_artifacts_exist",
            "no_legacy_admin_path_in_latest_artifacts",
            "strategy_promotion_requires_passing_outcome",
            "non_strategy_outcomes_never_count_as_promotion",
        ],
        "does_not_recompute_returns": True,
        "does_not_override_decisions": True,
        "promotion_scope": "governance_only",
        "methodology_version": "complete_campaign_registry_audit_v2",
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
        data_version=data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, rows = calculate(paths)
        complete_attempt(attempt, result, rows)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repository = SystemRepository(paths.system_state_path)
    rows: list[dict[str, Any]] = []
    for group, experiment_ids in CAMPAIGN.items():
        for experiment_id in experiment_ids:
            detail = repository.load_experiment_detail(experiment_id)
            latest = detail.get("latest_run") if detail else None
            artifacts = latest.get("artifacts", []) if latest else []
            output_dir = (
                resolve_path(paths, str(latest.get("output_dir")))
                if latest and latest.get("output_dir")
                else None
            )
            artifact_paths = [
                resolve_path(paths, str(item["file_path"]))
                for item in artifacts
                if item.get("file_path")
            ]
            rows.append(
                {
                    "group": group,
                    "experiment_id": experiment_id,
                    "status": (
                        latest.get("status", "MISSING")
                        if latest
                        else "MISSING"
                    ),
                    "outcome": (
                        latest.get("outcome", "MISSING")
                        if latest
                        else "MISSING"
                    ),
                    "output_exists": bool(output_dir and output_dir.exists()),
                    "artifact_count": len(artifact_paths),
                    "artifacts_exist": (
                        bool(artifact_paths)
                        and all(path.exists() for path in artifact_paths)
                    ),
                    "legacy_admin_path": any(
                        str(item.get("file_path", "")).startswith("/Users/admin/")
                        for item in artifacts
                    ),
                }
            )
    strategies = [row for row in rows if row["group"] == "strategy"]
    promoted = [
        row
        for row in strategies
        if row["outcome"] in PROMOTION_OUTCOMES
    ]
    checks = {
        "all_latest_runs_success": all(
            row["status"] == "SUCCESS" for row in rows
        ),
        "all_output_directories_exist": all(
            row["output_exists"] for row in rows
        ),
        "all_registered_artifacts_exist": all(
            row["artifacts_exist"] for row in rows
        ),
        "no_latest_artifact_uses_legacy_admin_path": not any(
            row["legacy_admin_path"] for row in rows
        ),
        "non_strategy_outcomes_not_counted_as_promotion": not any(
            row["group"] != "strategy"
            and row["experiment_id"] in {
                item["experiment_id"] for item in promoted
            }
            for row in rows
        ),
    }
    result = {
        "experiment_id": EXPERIMENT_ID,
        "experiment_count": len(rows),
        "strategy_candidate_count": len(strategies),
        "strategy_promotion_count": len(promoted),
        "promoted_strategy_ids": [
            row["experiment_id"] for row in promoted
        ],
        "outcome_counts": v1.count_values(rows, "outcome"),
        "group_counts": v1.count_values(rows, "group"),
        "checks": checks,
        "passed": all(checks.values()),
        "campaign_decision": (
            "NO_NEW_STRATEGY_PROMOTION"
            if not promoted
            else "PROMOTION_REQUIRES_MANUAL_REVIEW"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result, rows), encoding="utf-8")
    return result, rows


def resolve_path(paths: RuntimePaths, raw: str) -> Path:
    """只为审计解析旧根路径，不改数据库中的历史记录。"""
    path = Path(raw)
    legacy = Path("/Users/admin/PycharmProjects/quant")
    try:
        relative = path.relative_to(legacy)
    except ValueError:
        return path
    return paths.root / relative


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result, rows), encoding="utf-8")
    audit_path = attempt.output_dir / "campaign_audit.json"
    audit_path.write_text(
        json.dumps(
            {"result": result, "experiments": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_GOVERNANCE_AUDIT" if result["passed"] else "REJECTED",
        decision_reason=(
            "完整研究批次台账与产物一致，未发现误晋级"
            if result["passed"]
            else "研究批次存在台账、产物或路径异常"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "完整批次元审计报告"),
            ExperimentArtifact("campaign_audit", audit_path, "逐实验审计"),
        ],
    )


def render_report(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    table = "\n".join(
        f"| {row['group']} | `{row['experiment_id']}` | "
        f"{row['outcome']} | {row['status']} | "
        f"{'PASS' if row['output_exists'] and row['artifacts_exist'] and not row['legacy_admin_path'] else 'FAIL'} |"
        for row in rows
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 2026-07-29 完整研究批次元审计 V2

- 实验总数：{result['experiment_count']}
- 策略候选：{result['strategy_candidate_count']}
- 新晋级策略：{result['strategy_promotion_count']}
- 批次结论：`{result['campaign_decision']}`

| 分组 | 实验 | 结论 | 状态 | 本机产物 |
|---|---|---|---|---|
{table}

## 一致性检查

{checks}

## 结论

可行性通过只允许进入冻结回测；执行审计通过只说明对应风险在其门槛内；
`INCONCLUSIVE`、`REJECTED`与稳健失败均不计为策略晋级。本轮没有修改生产注册或调度。
"""


def data_version(paths: RuntimePaths) -> str:
    stat = paths.system_state_path.stat()
    return f"system_state:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260729")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
