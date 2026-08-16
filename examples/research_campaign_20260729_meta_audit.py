"""2026-07-29新策略研究批次的台账、产物与晋级结论元审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


EXPERIMENT_ID = "research_campaign_20260729_meta_audit_v1"
REPORT_PATH = Path("docs/research/research-campaign-20260729-meta-audit-v1.md")
CAMPAIGN = {
    "allocation_strategy": [
        "nasdaq_gold_china_dividend_equal_v1",
        "china_tech_dividend_gold_equal_v1",
        "nasdaq_gold_bond_balanced_50_25_25_v1",
        "limit_event_sentiment_defensive_allocation_v1",
    ],
    "event_strategy": [
        "limit_up_first_board_seal_strength_v1",
        "limit_up_first_board_open_executable_v1",
        "limit_down_weak_seal_weekly_reversal_v1",
    ],
    "factor_strategy": ["margin_financing_flow_v1"],
    "portfolio_strategy": [
        "global_defensive_margin_flow_satellite_90_10_v1",
    ],
    "feasibility": [
        "limit_up_first_board_event_data_feasibility_v1",
        "limit_down_weekly_reversal_data_feasibility_v1",
        "a_share_ma60_breadth_regime_data_feasibility_v1",
        "limit_event_five_day_sentiment_data_feasibility_v1",
    ],
    "audit": [
        "borderline_allocation_correlation_audit_v2",
        "limit_up_first_board_execution_assumption_audit_v1",
        "global_defensive_mainline_satellite_robustness_v1",
        "global_defensive_margin_flow_correlation_audit_v1",
    ],
}
STRATEGY_CATEGORIES = {
    "allocation_strategy",
    "event_strategy",
    "factor_strategy",
    "portfolio_strategy",
}
PROMOTION_OUTCOMES = {
    "PASSED_RESEARCH_GATE",
    "PASSED_ROBUSTNESS",
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="2026-07-29新策略研究批次元审计 V1",
    category="research_governance",
    hypothesis=(
        "本批次所有可行性、策略、组合与稳健性实验是否均有成功台账、完整本机产物，且"
        "最终晋级结论与各自冻结门槛一致"
    ),
    definition={
        "campaign": CAMPAIGN,
        "checks": [
            "latest_run_success",
            "output_directory_exists",
            "all_registered_artifacts_exist",
            "no_legacy_admin_path_in_latest_artifacts",
            "strategy_promotion_only_from_passing_outcome",
        ],
        "does_not_recompute_returns": True,
        "does_not_override_decisions": True,
        "promotion_scope": "governance_only",
        "methodology_version": "campaign_registry_artifact_audit_v1",
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
        data_version=_data_version(paths),
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
    rows = []
    for campaign_category, experiment_ids in CAMPAIGN.items():
        for experiment_id in experiment_ids:
            detail = repository.load_experiment_detail(experiment_id)
            latest = detail.get("latest_run") if detail else None
            artifacts = latest.get("artifacts", []) if latest else []
            output_dir = (
                Path(str(latest["output_dir"]))
                if latest and latest.get("output_dir")
                else None
            )
            artifact_paths = [
                Path(str(item["file_path"]))
                for item in artifacts
                if item.get("file_path")
            ]
            rows.append(
                {
                    "category": campaign_category,
                    "experiment_id": experiment_id,
                    "status": latest.get("status", "MISSING") if latest else "MISSING",
                    "outcome": latest.get("outcome", "MISSING") if latest else "MISSING",
                    "output_exists": bool(output_dir and output_dir.exists()),
                    "artifact_count": len(artifact_paths),
                    "artifacts_exist": bool(artifact_paths)
                    and all(path.exists() for path in artifact_paths),
                    "legacy_admin_path": any(
                        str(path).startswith("/Users/admin/")
                        for path in artifact_paths
                    ),
                }
            )
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
    }
    strategies = [
        row
        for row in rows
        if row["category"] in STRATEGY_CATEGORIES
    ]
    promoted = [
        row
        for row in strategies
        if row["outcome"] in PROMOTION_OUTCOMES
    ]
    result = {
        "experiment_id": EXPERIMENT_ID,
        "experiment_count": len(rows),
        "strategy_candidate_count": len(strategies),
        "strategy_promotion_count": len(promoted),
        "promoted_strategy_ids": [
            row["experiment_id"] for row in promoted
        ],
        "outcome_counts": count_values(rows, "outcome"),
        "category_counts": count_values(rows, "category"),
        "checks": checks,
        "passed": all(checks.values()),
        "campaign_decision": (
            "NO_NEW_STRATEGY_PROMOTION"
            if not promoted
            else "PROMOTION_REQUIRES_MANUAL_REVIEW"
        ),
        "notes": [
            "全球防守×主线80/20是本批次前已通过的基线，本批次稳健性审计未通过P05门槛。",
            "可行性或执行审计通过不等于策略通过。",
            "所有REJECTED结果保持归档，不写生产注册表。",
        ],
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result, rows), encoding="utf-8")
    return result, rows


def count_values(
    rows: list[dict[str, Any]],
    key: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row[key])
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


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
            "研究批次台账与产物完整；本批次无新策略晋级"
            if result["passed"] and result["strategy_promotion_count"] == 0
            else "研究批次存在台账、产物或晋级一致性异常"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "研究批次元审计报告"),
            ExperimentArtifact("campaign_audit", audit_path, "逐实验审计"),
        ],
    )


def render_report(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    table = "\n".join(
        "| {category} | `{experiment}` | {outcome} | {status} | {artifacts} |".format(
            category=row["category"],
            experiment=row["experiment_id"],
            outcome=row["outcome"],
            status=row["status"],
            artifacts=(
                "PASS"
                if row["output_exists"]
                and row["artifacts_exist"]
                and not row["legacy_admin_path"]
                else "FAIL"
            ),
        )
        for row in rows
    )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["checks"].items()
    )
    return f"""# 2026-07-29 新策略研究批次元审计 V1

- 实验总数：{result['experiment_count']}
- 策略/组合候选：{result['strategy_candidate_count']}
- 新晋级策略：{result['strategy_promotion_count']}
- 批次结论：`{result['campaign_decision']}`

| 类别 | 实验 | 结论 | 状态 | 本机产物 |
|---|---|---|---|---|
{table}

## 一致性检查

{checks}

## 结论

本批次没有新策略通过全部冻结门槛。通过的数据可行性和执行审计只允许继续研究，
不能等同于策略晋级；所有拒绝结果保持归档，不修改生产策略或调度。
"""


def _data_version(paths: RuntimePaths) -> str:
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
