"""归因交易活跃度稳定性因子的回撤、换手与近期失效。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import trading_activity_stability_study as source
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


EXPERIMENT_ID = "trading_activity_stability_failure_attribution_audit_v1"
REPORT_PATH = Path(
    "docs/research/trading-activity-stability-failure-attribution-audit-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="交易活跃度稳定性失败归因 V1",
    category="research_audit",
    hypothesis=(
        "候选失败是否同时由深回撤、高换手、近期弱化与既有质量策略重叠"
        "构成，而非单纯交易成本可解释"
    ),
    definition={
        "source_strategy": source.STRATEGY_ID,
        "expected_source_outcome": "REJECTED",
        "reads_repository_metrics_only": True,
        "frozen_attribution_checks": {
            "full_drawdown_shortfall_min": 0.05,
            "turnover_multiple_of_limit_min": 1.50,
            "execution_cost_impact_min": 0.50,
            "recent_fold_annual_return_max": 0.08,
            "latest_year_return_max": 0.0,
            "quality_correlation_above_gate": True,
        },
        "forbidden_followups": [
            "change_factor_direction",
            "change_lookback",
            "change_top_n",
            "change_rebalance_frequency",
            "change_risk_overlay",
            "change_sample",
        ],
        "does_not_change_source_gate": True,
        "does_not_run_variants": True,
        "does_not_promote_strategy": True,
        "promotion_scope": "failure_attribution_only",
        "methodology_version": "registered_metrics_failure_map_v1",
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
        source.STRATEGY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("交易活跃度稳定性策略依赖尚未成功")
    if latest.get("outcome") != "REJECTED":
        raise RuntimeError(
            f"交易活跃度稳定性策略并未拒绝: {latest.get('outcome')}"
        )
    return dict(latest.get("metrics") or {})


def calculate(
    metrics: dict[str, Any],
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, Any]:
    full = metrics["period_metrics"]["full"]
    recent = metrics["period_metrics"]["2024_latest"]
    latest_year = metrics["annual_metrics"][max(metrics["annual_metrics"])]
    drawdown_shortfall = abs(float(full["max_drawdown"])) - 0.30
    turnover_multiple = float(full["annual_turnover"]) / 10.0
    failed = sorted(
        name
        for name, passed in metrics["gate"]["checks"].items()
        if not passed
    )
    checks = {
        "full_drawdown_misses_by_at_least_5pct": drawdown_shortfall >= 0.05,
        "turnover_is_at_least_1_5x_limit": turnover_multiple >= 1.50,
        "execution_cost_impact_at_least_50pct": (
            float(full["execution_cost_impact"]) >= 0.50
        ),
        "recent_fold_return_below_8pct": (
            float(recent["annualized_return"]) < 0.08
        ),
        "latest_year_return_negative": (
            float(latest_year["annualized_return"]) < 0.0
        ),
        "quality_correlation_exceeds_gate": (
            float(metrics["quality_return_correlation"]) > 0.75
        ),
        "source_has_multiple_economic_gate_failures": len(failed) >= 4,
    }
    broad_failure = all(checks.values())
    return {
        "as_of_date": as_of_date,
        "source_decision": "REJECTED",
        "failed_checks": failed,
        "full_annualized_return": float(full["annualized_return"]),
        "full_sharpe": float(full["sharpe"]),
        "full_max_drawdown": float(full["max_drawdown"]),
        "drawdown_shortfall": float(drawdown_shortfall),
        "full_annual_turnover": float(full["annual_turnover"]),
        "turnover_multiple_of_limit": float(turnover_multiple),
        "full_execution_cost_impact": float(full["execution_cost_impact"]),
        "recent_fold_annualized_return": float(recent["annualized_return"]),
        "latest_year_annualized_return": float(
            latest_year["annualized_return"]
        ),
        "quality_return_correlation": float(
            metrics["quality_return_correlation"]
        ),
        "checks": checks,
        "classification": (
            "BROAD_RISK_TURNOVER_AND_RECENT_RETURN_FAILURE"
            if broad_failure
            else "PARTIAL_OR_UNRESOLVED_FAILURE"
        ),
        "cost_only_explanation": False,
        "source_rejection_overridden": False,
        "variants_run": False,
        "strategy_promoted": False,
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
    metrics_path = attempt.output_dir / "failure_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "深回撤、高换手、近期弱化和策略重叠共同失败，禁止后续变体"
            if result["classification"].startswith("BROAD_")
            else "失败归因不完整但来源拒绝保持，禁止后续变体"
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
    return f"""# 交易活跃度稳定性失败归因 V1

- 来源决策：`{result['source_decision']}`；分类：
  `{result['classification']}`。
- 全期年化/Sharpe/回撤：
  {result['full_annualized_return']:.2%} /
  {result['full_sharpe']:.3f} /
  {result['full_max_drawdown']:.2%}。
- 回撤门槛短缺：{result['drawdown_shortfall']:.2%}。
- 年换手：{result['full_annual_turnover']:.2f}x，为门槛
  {result['turnover_multiple_of_limit']:.2f}倍；全期成本影响：
  {result['full_execution_cost_impact']:.2%}。
- 2024至今/最新年年化：
  {result['recent_fold_annualized_return']:.2%} /
  {result['latest_year_annualized_return']:.2%}。
- 与质量策略收益相关：
  {result['quality_return_correlation']:.4f}。

## 冻结归因检查

{checks}

该失败不是成本单因子解释。按预注册规则，不运行方向、窗口、TopN、
调仓频率、风险层或样本变体。
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
