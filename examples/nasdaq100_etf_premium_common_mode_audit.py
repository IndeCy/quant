"""境内纳指100 ETF当前溢价的横截面共同模式审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq100_domestic_etf_execution_feasibility_study as source
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


EXPERIMENT_ID = "nasdaq100_etf_premium_common_mode_audit_v1"
REPORT_PATH = Path(
    "docs/research/nasdaq100-etf-premium-common-mode-audit-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="境内纳指100 ETF溢价共同模式审计 V1",
    category="execution_audit",
    hypothesis=(
        "替代载体全部失败是否由跨基金共同的高溢价状态造成，而不是159941"
        "单一基金的流动性或定价问题"
    ),
    definition={
        "source_feasibility": source.EXPERIMENT_ID,
        "reads_source_metrics_only": True,
        "common_mode_checks": {
            "candidate_count_min": 10,
            "share_above_5pct_min": 0.90,
            "cross_section_median_premium_min": 0.08,
            "cross_section_premium_range_max": 0.04,
            "liquid_capacity_pass_but_premium_fail_count_min": 8,
        },
        "does_not_infer_causal_quota_without_primary_data": True,
        "does_not_authorize_lowest_premium_substitution": True,
        "promotion_scope": "execution_common_mode_only",
        "methodology_version": "current_cross_section_v1",
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
        result, candidates = calculate(metrics, paths)
        complete_attempt(attempt, result, candidates)
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
        raise RuntimeError("纳指100替代载体可行性依赖尚未成功")
    if latest.get("outcome") != "REJECTED":
        raise RuntimeError(
            f"替代载体研究未拒绝: {latest.get('outcome')}"
        )
    return dict(latest.get("metrics") or {})


def calculate(
    metrics: dict[str, Any],
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame]:
    candidates = pd.DataFrame(metrics["candidates"]).copy()
    premium = pd.to_numeric(candidates["latest_premium"], errors="coerce")
    valid = candidates[premium.notna()].copy()
    valid["latest_premium"] = premium[premium.notna()]
    liquid_capacity = valid.apply(
        lambda row: (
            bool(row["checks"]["median_20d_amount_at_least_100m"])
            and bool(
                row["checks"]["one_million_participation_within_1pct"]
            )
        ),
        axis=1,
    )
    premium_fail = valid["latest_premium"].abs().gt(0.05)
    liquid_but_premium_fail = int((liquid_capacity & premium_fail).sum())
    premium_range = float(
        valid["latest_premium"].max() - valid["latest_premium"].min()
    )
    share_above = float(premium_fail.mean())
    median = float(valid["latest_premium"].median())
    checks = {
        "at_least_ten_candidates": len(valid) >= 10,
        "at_least_90pct_above_5pct_premium": share_above >= 0.90,
        "median_premium_at_least_8pct": median >= 0.08,
        "premium_cross_section_range_within_4pct": premium_range <= 0.04,
        "at_least_eight_liquid_capacity_pass_but_premium_fail": (
            liquid_but_premium_fail >= 8
        ),
    }
    common_mode = all(checks.values())
    lowest = valid.nsmallest(1, "latest_premium").iloc[0]
    highest = valid.nlargest(1, "latest_premium").iloc[0]
    result = {
        "candidate_count": int(len(valid)),
        "share_above_5pct_premium": share_above,
        "median_premium": median,
        "minimum_premium": float(lowest["latest_premium"]),
        "minimum_premium_symbol": str(lowest["symbol"]),
        "maximum_premium": float(highest["latest_premium"]),
        "maximum_premium_symbol": str(highest["symbol"]),
        "premium_cross_section_range": premium_range,
        "liquid_capacity_pass_but_premium_fail_count": (
            liquid_but_premium_fail
        ),
        "checks": checks,
        "classification": (
            "SYSTEM_WIDE_NASDAQ100_QDII_PREMIUM_REGIME"
            if common_mode
            else "FUND_SPECIFIC_OR_MIXED_PREMIUM_REGIME"
        ),
        "causal_quota_claimed": False,
        "substitution_authorized": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, valid


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    candidates: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    candidates_path = attempt.output_dir / "premium_cross_section.csv"
    candidates.to_csv(candidates_path, index=False)
    metrics_path = attempt.output_dir / "common_mode_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "纳指100ETF当前高溢价为跨基金共同状态，换代码不能满足5%门槛"
            if result["classification"].startswith("SYSTEM_WIDE")
            else "当前高溢价在基金间差异较大，不能确认为共同模式"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "溢价共同模式报告"),
            ExperimentArtifact("cross_section", candidates_path, "横截面明细"),
            ExperimentArtifact("metrics", metrics_path, "共同模式指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 境内纳指100 ETF溢价共同模式审计 V1

- 候选：{result['candidate_count']}只。
- 溢价超过5%的占比：{result['share_above_5pct_premium']:.1%}。
- 溢价中位：{result['median_premium']:.2%}。
- 最低：{result['minimum_premium_symbol']}
  {result['minimum_premium']:.2%}；最高：
  {result['maximum_premium_symbol']} {result['maximum_premium']:.2%}。
- 横截面范围：{result['premium_cross_section_range']:.2%}。
- 流动性和容量通过、仅溢价失败：
  {result['liquid_capacity_pass_but_premium_fail_count']}只。
- 分类：`{result['classification']}`。

## 共同模式门槛

{checks}

横截面共同状态支持“换另一只纳指100 ETF不能解决当前溢价门槛”，但没有
申购额度等一级数据，因此不把具体因果武断归为QDII额度限制，也不授权替换。
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
