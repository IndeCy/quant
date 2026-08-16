"""2026-07-29研究批次含容量与当前溢价证据的最终元审计 V3。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import research_campaign_20260729_meta_audit as v1
from examples import research_campaign_20260729_meta_audit_v2 as v2
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


EXPERIMENT_ID = "research_campaign_20260729_meta_audit_v3"
REPORT_PATH = Path("docs/research/research-campaign-20260729-meta-audit-v3.md")
CAMPAIGN = {group: list(values) for group, values in v2.CAMPAIGN.items()}
CAMPAIGN["strategy"].append(
    "intraday_strength_vs_overnight_20d_v1"
)
CAMPAIGN["strategy"].append(
    "sp500_gold_60_40_vol_target_12_v1"
)
CAMPAIGN["strategy"].append(
    "trading_activity_stability_v1"
)
CAMPAIGN["feasibility"].append(
    "nasdaq100_domestic_etf_execution_feasibility_v1"
)
CAMPAIGN["feasibility"].append(
    "sp500_domestic_etf_execution_feasibility_v1"
)
CAMPAIGN["feasibility"].append(
    "cross_asset_independent_trend_data_feasibility_v1"
)
CAMPAIGN["feasibility"].append(
    "trading_activity_stability_data_feasibility_v1"
)
CAMPAIGN["audit"].extend(
    [
        "nasdaq_gold_60_40_capacity_execution_audit_v1",
        "nasdaq_gold_60_40_capacity_failure_attribution_audit_v1",
        "nasdaq_gold_60_40_post_capacity_recovery_audit_v1",
        "nasdaq_gold_60_40_sp500_capacity_comparison_audit_v1",
        "qdii_current_nav_monitoring_audit_v1",
        "qdii_current_premium_window_audit_v2",
        "intraday_strength_failure_attribution_audit_v1",
        "nasdaq100_etf_premium_common_mode_audit_v1",
        "sp500_etf_513650_513500_instrument_equivalence_audit_v1",
        "sp500_etf_premium_tracking_attribution_audit_v1",
        "sp500_etf_premium_normalization_risk_audit_v1",
        "sp500_premium_normalization_robustness_audit_v1",
        "sp500_gold_vol_target_failure_attribution_audit_v1",
        "sp500_gold_vol_target_statistical_audit_v1",
        "cross_asset_independent_trend_feasibility_failure_audit_v1",
        "trading_activity_stability_failure_attribution_audit_v1",
    ]
)
CAMPAIGN["governance"].extend(
    [
        v2.EXPERIMENT_ID,
        "factor_research_meta_audit_v1",
        "a_share_factor_turnover_regime_audit_v1",
        "a_share_factor_turnover_statistical_audit_v1",
        "factor_zoo_common_mode_attribution_v1",
        "factor_zoo_holdings_size_attribution_v1",
        "factor_zoo_walk_forward_midcap_residual_v1",
        "research_campaign_20260729_decision_memo_v1",
    ]
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="2026-07-29研究批次最终元审计 V3",
    category="research_governance",
    hypothesis=(
        "全部策略、门禁、容量、当前折溢价和统计审计是否具备本机成功台账，且"
        "执行审计的通过或风险标记均未被误计为策略晋级"
    ),
    definition={
        "campaign": CAMPAIGN,
        "checks": [
            "latest_run_success",
            "output_directory_exists",
            "all_registered_artifacts_exist",
            "no_legacy_admin_path_in_latest_artifacts",
            "only_strategy_group_can_count_as_promotion",
            "risk_flagged_audits_preserved",
        ],
        "does_not_recompute_returns": True,
        "does_not_override_decisions": True,
        "promotion_scope": "governance_only",
        "methodology_version": "capacity_and_current_premium_campaign_v3",
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
                v2.resolve_path(paths, str(latest.get("output_dir")))
                if latest and latest.get("output_dir")
                else None
            )
            artifact_paths = [
                v2.resolve_path(paths, str(item["file_path"]))
                for item in artifacts
                if item.get("file_path")
            ]
            rows.append(
                {
                    "group": group,
                    "experiment_id": experiment_id,
                    "status": (
                        str(latest.get("status", "MISSING"))
                        if latest
                        else "MISSING"
                    ),
                    "outcome": (
                        str(latest.get("outcome", "MISSING"))
                        if latest
                        else "MISSING"
                    ),
                    "output_exists": bool(
                        output_dir and output_dir.exists()
                    ),
                    "artifact_count": len(artifact_paths),
                    "artifacts_exist": bool(artifact_paths)
                    and all(path.exists() for path in artifact_paths),
                    "legacy_admin_path": any(
                        str(item.get("file_path", "")).startswith(
                            "/Users/admin/"
                        )
                        for item in artifacts
                    ),
                }
            )
    strategies = [row for row in rows if row["group"] == "strategy"]
    promoted = [
        row
        for row in strategies
        if row["outcome"] in v2.PROMOTION_OUTCOMES
    ]
    audit_risks = [
        row
        for row in rows
        if row["group"] == "audit" and row["outcome"] == "RISK_FLAGGED"
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
        "only_strategy_group_counted_as_promotion": all(
            row["group"] == "strategy" for row in promoted
        ),
        "current_execution_risk_flags_preserved": {
            row["experiment_id"] for row in audit_risks
        }.issuperset(
            {
                "nasdaq_gold_60_40_capacity_execution_audit_v1",
                "qdii_current_nav_monitoring_audit_v1",
                "qdii_current_premium_window_audit_v2",
            }
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
        "risk_flagged_audit_ids": [
            row["experiment_id"] for row in audit_risks
        ],
        "outcome_counts": v1.count_values(rows, "outcome"),
        "group_counts": v1.count_values(rows, "group"),
        "checks": checks,
        "passed": all(checks.values()),
        "campaign_decision": (
            "NO_NEW_STRATEGY_PROMOTION_CURRENT_EXECUTION_RISKS_OPEN"
            if not promoted and audit_risks
            else "MANUAL_REVIEW_REQUIRED"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result, rows), encoding="utf-8")
    return result, rows


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
        outcome=(
            "PASSED_GOVERNANCE_AUDIT" if result["passed"] else "REJECTED"
        ),
        decision_reason=(
            "完整研究台账一致，当前容量与溢价风险标记均保留且无误晋级"
            if result["passed"]
            else "研究批次存在台账、产物、路径或风险标记异常"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "最终批次元审计"),
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
    return f"""# 2026-07-29研究批次最终元审计 V3

- 实验总数：{result['experiment_count']}。
- 策略候选：{result['strategy_candidate_count']}；晋级：
  {result['strategy_promotion_count']}。
- 当前执行风险：{', '.join(result['risk_flagged_audit_ids']) or '无'}。
- 决策：`{result['campaign_decision']}`。

## 一致性门槛

{checks}

| 分组 | 实验 | 结论 | 状态 | 产物/路径 |
|---|---|---|---|---|
{table}
"""


def data_version(paths: RuntimePaths) -> str:
    state = paths.system_state_path.stat()
    return f"{state.st_size}:{state.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_study(
                get_runtime_paths(),
                args.as_of_date,
                force=args.force,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
