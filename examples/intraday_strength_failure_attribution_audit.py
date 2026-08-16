"""日内强度减隔夜情绪策略的失败来源与符号稳定性审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import intraday_strength_study as source
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


EXPERIMENT_ID = "intraday_strength_failure_attribution_audit_v1"
REPORT_PATH = Path(
    "docs/research/intraday-strength-failure-attribution-audit-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="日内强度减隔夜情绪失败归因 V1",
    category="failure_attribution",
    hypothesis=(
        "源策略的极端负收益是否由数据恒等式、单一时期或交易成本造成，还是"
        "在训练、验证和锁定样本均稳定为负的经济方向失败"
    ),
    definition={
        "source_strategy": source.STRATEGY_ID,
        "reads_source_metrics_only": True,
        "return_recompute": False,
        "checks": {
            "data_identity_passed": True,
            "all_train_validation_locked_returns_negative": True,
            "positive_years_max": 2,
            "full_execution_cost_impact_max": 0.25,
            "full_drawdown_below_minus_80pct": True,
        },
        "prohibited_followups": [
            "invert_factor_after_observing_returns",
            "change_window",
            "change_top_n",
            "change_sample_period",
        ],
        "does_not_override_source_rejection": True,
        "promotion_scope": "failure_attribution_only",
        "methodology_version": "source_metrics_sign_audit_v1",
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
        result = calculate(metrics, paths)
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
        raise RuntimeError("日内强度源研究尚未成功")
    if latest.get("outcome") != "REJECTED":
        raise RuntimeError(
            f"日内强度源研究未拒绝: {latest.get('outcome')}"
        )
    return dict(latest.get("metrics") or {})


def calculate(
    metrics: dict[str, Any],
    paths: RuntimePaths,
) -> dict[str, Any]:
    periods = metrics["period_metrics"]
    annual = metrics["annual_metrics"]
    full = periods["full"]
    sign_periods = ["train", "validation", "locked_test"]
    checks = {
        "data_identity_passed": bool(metrics["data_quality"]["passed"]),
        "all_train_validation_locked_returns_negative": all(
            periods[name]["annualized_return"] < 0 for name in sign_periods
        ),
        "positive_years_at_most_two": (
            sum(item["annualized_return"] > 0 for item in annual.values()) <= 2
        ),
        "full_execution_cost_impact_within_25pct": (
            full["execution_cost_impact"] <= 0.25
        ),
        "full_drawdown_below_minus_80pct": full["max_drawdown"] <= -0.80,
    }
    economic_sign_failure = all(checks.values())
    return {
        "source_strategy": source.STRATEGY_ID,
        "source_outcome": "REJECTED",
        "period_returns": {
            name: float(periods[name]["annualized_return"])
            for name in [*sign_periods, "full"]
        },
        "full_max_drawdown": float(full["max_drawdown"]),
        "full_execution_cost_impact": float(
            full["execution_cost_impact"]
        ),
        "positive_years": sum(
            item["annualized_return"] > 0 for item in annual.values()
        ),
        "data_identity_error": float(
            metrics["data_quality"]["max_identity_error"]
        ),
        "median_spearman_with_ret20": float(
            metrics["diagnostics"]["median_spearman_with_ret20"]
        ),
        "checks": checks,
        "classification": (
            "ROBUST_ECONOMIC_SIGN_FAILURE_NOT_COST_ARTIFACT"
            if economic_sign_failure
            else "INCONCLUSIVE"
        ),
        "source_rejection_overridden": False,
        "followup_variants_allowed": False,
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
    metrics_path = attempt.output_dir / "failure_attribution.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "负收益跨训练、验证和锁定样本稳定，且非数据恒等式或成本单独造成"
            if result["classification"].startswith("ROBUST_")
            else "现有源指标不足以确定失败来源"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "失败归因报告"),
            ExperimentArtifact("metrics", metrics_path, "失败归因指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {name} | {value:.2%} |"
        for name, value in result["period_returns"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 日内强度减隔夜情绪失败归因 V1

- 分类：{result['classification']}。
- 全期最大回撤：{result['full_max_drawdown']:.2%}。
- 全期成本影响：{result['full_execution_cost_impact']:.2%}。
- 正收益年度：{result['positive_years']}。
- 收益分解恒等式最大误差：{result['data_identity_error']:.3e}。
- 与20日动量秩相关中位：{result['median_spearman_with_ret20']:.3f}。

| 样本 | 年化收益 |
|---|---:|
{periods}

## 失败归因门槛

{checks}

源策略保持拒绝；禁止在看到结果后反转因子方向、改窗口、改TopN或改样本期。
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
