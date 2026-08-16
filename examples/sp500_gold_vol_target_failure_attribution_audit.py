"""归因标普黄金12%波动目标候选的冻结门槛失败。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import sp500_gold_vol_target_study as source
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


EXPERIMENT_ID = "sp500_gold_vol_target_failure_attribution_audit_v1"
REPORT_PATH = Path(
    "docs/research/sp500-gold-vol-target-failure-attribution-audit-v1.md"
)
EXPECTED_FAILED_CHECKS = {
    "oos_drawdown_within_20pct",
    "worst_fold_drawdown_within_20pct",
    "annual_turnover_below_15x",
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="标普黄金波动目标失败归因 V1",
    category="research_audit",
    hypothesis=(
        "该候选的三个失败门槛是否主要由同一2020回撤事件被全期与折叠重复"
        "呈现，加上轻微换手超限构成，而非广泛的收益、风险或成本失败"
    ),
    definition={
        "source_strategy": source.EXPERIMENT_ID,
        "expected_source_outcome": "REJECTED",
        "reads_repository_metrics_only": True,
        "frozen_attribution_rules": {
            "expected_failed_checks": sorted(EXPECTED_FAILED_CHECKS),
            "drawdown_shortfall_max": 0.005,
            "oos_and_worst_fold_drawdown_match_tolerance": 1e-12,
            "annual_turnover_excess_max": 0.20,
            "same_mechanism_return_lift_positive": True,
            "same_mechanism_sharpe_lift_positive": True,
            "direct_sp500_drawdown_improvement_positive": True,
        },
        "does_not_change_source_gate": True,
        "does_not_change_parameters": True,
        "does_not_promote_strategy": True,
        "promotion_scope": "failure_attribution_only",
        "methodology_version": "repository_gate_failure_attribution_v1",
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
        metrics = load_source_metrics(paths)
        result = calculate(metrics, paths, as_of_date)
        complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def load_source_metrics(paths: RuntimePaths) -> dict[str, Any]:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("标普黄金波动目标依赖尚未成功")
    if latest.get("outcome") != "REJECTED":
        raise RuntimeError(
            f"标普黄金波动目标并未拒绝: {latest.get('outcome')}"
        )
    return dict(latest.get("metrics") or {})


def calculate(
    metrics: dict[str, Any],
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, Any]:
    gate = metrics["gate"]
    failed = {
        name for name, passed in gate["checks"].items() if not passed
    }
    oos = metrics["period_metrics"]["oos_full"]
    fold = metrics["period_metrics"]["2019_2021"]
    drawdown_shortfall = abs(float(oos["max_drawdown"])) - 0.20
    turnover_excess = float(oos["annual_turnover"]) - 1.50
    annual = metrics["annual_comparison"][source.EXPERIMENT_ID]
    worst_year = min(
        annual,
        key=lambda year: float(annual[year]["max_drawdown"]),
    )
    checks = {
        "only_expected_checks_failed": failed == EXPECTED_FAILED_CHECKS,
        "drawdown_shortfall_within_half_percent": (
            0.0 < drawdown_shortfall <= 0.005
        ),
        "oos_and_worst_fold_share_same_drawdown": (
            abs(
                float(oos["max_drawdown"])
                - float(fold["max_drawdown"])
            )
            <= 1e-12
        ),
        "worst_drawdown_year_is_2020": worst_year == "2020",
        "turnover_excess_within_point_two": (
            0.0 < turnover_excess <= 0.20
        ),
        "same_mechanism_return_lift_positive": (
            float(gate["return_lift_vs_vol_target_control"]) > 0.0
        ),
        "same_mechanism_sharpe_lift_positive": (
            float(gate["sharpe_lift_vs_vol_target_control"]) > 0.0
        ),
        "direct_sp500_drawdown_improvement_positive": (
            float(gate["drawdown_improvement_vs_direct_sp500"]) > 0.0
        ),
    }
    concentrated = all(checks.values())
    return {
        "as_of_date": as_of_date,
        "source_decision": metrics["decision"],
        "failed_checks": sorted(failed),
        "failed_check_count": len(failed),
        "economic_failure_clusters": (
            ["2020_drawdown", "annual_turnover"]
            if concentrated
            else ["multiple_or_unresolved"]
        ),
        "oos_annualized_return": float(oos["annualized_return"]),
        "oos_sharpe": float(oos["sharpe"]),
        "oos_max_drawdown": float(oos["max_drawdown"]),
        "drawdown_shortfall": float(drawdown_shortfall),
        "worst_drawdown_year": worst_year,
        "oos_annual_turnover": float(oos["annual_turnover"]),
        "turnover_excess": float(turnover_excess),
        "return_lift_vs_same_mechanism_control": float(
            gate["return_lift_vs_vol_target_control"]
        ),
        "sharpe_lift_vs_same_mechanism_control": float(
            gate["sharpe_lift_vs_vol_target_control"]
        ),
        "drawdown_improvement_vs_direct_sp500": float(
            gate["drawdown_improvement_vs_direct_sp500"]
        ),
        "checks": checks,
        "classification": (
            "CONCENTRATED_BORDERLINE_REJECTION"
            if concentrated
            else "BROAD_OR_UNRESOLVED_REJECTION"
        ),
        "source_rejection_overridden": False,
        "strategy_promoted": False,
        "parameters_changed": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    metrics_path = attempt.output_dir / "failure_attribution_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "失败集中在同一2020回撤与轻微换手超限，但冻结拒绝保持"
            if result["classification"] == "CONCENTRATED_BORDERLINE_REJECTION"
            else "失败未能归并为少数边界经济问题，冻结拒绝保持"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "失败归因报告"),
            ExperimentArtifact("metrics", metrics_path, "失败归因指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 标普黄金波动目标失败归因 V1

- 来源结论：`{result['source_decision']}`；失败门槛：
  {', '.join(result['failed_checks'])}。
- 经济失败簇：{', '.join(result['economic_failure_clusters'])}。
- OOS年化/Sharpe/回撤：
  {result['oos_annualized_return']:.2%} /
  {result['oos_sharpe']:.3f} /
  {result['oos_max_drawdown']:.2%}。
- 回撤门槛短缺：{result['drawdown_shortfall']:.2%}；最差年份：
  {result['worst_drawdown_year']}。
- 年换手：{result['oos_annual_turnover']:.2f}x；超限：
  {result['turnover_excess']:.2f}x。
- 相对同机制标普收益/Sharpe提升：
  {result['return_lift_vs_same_mechanism_control']:.2%} /
  {result['sharpe_lift_vs_same_mechanism_control']:.3f}。
- 相对直接标普回撤改善：
  {result['drawdown_improvement_vs_direct_sp500']:.2%}。
- 分类：`{result['classification']}`。

## 归因检查

{checks}

边界失败仍是失败。本审计不调整门槛、参数或生产注册，也不授权晋级。
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
