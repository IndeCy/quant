"""A股因子研究按年换手分层的锁定期存活审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import factor_research_meta_audit as source
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


EXPERIMENT_ID = "a_share_factor_turnover_regime_audit_v1"
REPORT_PATH = Path(
    "docs/research/a-share-factor-turnover-regime-audit-v1.md"
)
BUCKETS = {
    "low_le_8x": (float("-inf"), 8.0),
    "medium_8_to_15x": (8.0, 15.0),
    "high_gt_15x": (15.0, float("inf")),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="A股因子换手分层锁定期存活审计 V1",
    category="research_governance",
    hypothesis=(
        "较低年换手是否能显著改善31个因子家族的锁定期收益和正收益比例，"
        "以及低频本身是否足以产生通过门槛的策略"
    ),
    definition={
        "source_meta_audit": source.EXPERIMENT_ID,
        "turnover_buckets": {
            "low_le_8x": "annual_turnover<=8",
            "medium_8_to_15x": "8<annual_turnover<=15",
            "high_gt_15x": "annual_turnover>15",
        },
        "descriptive_only": True,
        "checks": {
            "source_experiments_min": 30,
            "all_buckets_nonempty": True,
            "low_minus_high_locked_return_min_for_evidence": 0.03,
            "low_positive_ratio_must_exceed_high": True,
        },
        "does_not_reclassify_source_strategies": True,
        "promotion_scope": "meta_evidence_only",
        "methodology_version": "fixed_turnover_buckets_v1",
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
        rows = load_source_rows(paths)
        result, classified = calculate(rows, paths)
        complete_attempt(attempt, result, classified)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def load_source_rows(paths: RuntimePaths) -> list[dict[str, Any]]:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("跨因子元审计依赖尚未成功")
    metrics = latest.get("metrics") or {}
    rows = metrics.get("experiment_rows") or []
    if len(rows) < 30:
        raise RuntimeError(f"跨因子元审计样本不足: {len(rows)}")
    return list(rows)


def calculate(
    rows: list[dict[str, Any]],
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame]:
    frame = pd.DataFrame(rows).copy()
    frame["turnover_bucket"] = frame["full_turnover"].map(
        classify_turnover
    )
    summaries = []
    for bucket in BUCKETS:
        values = frame[frame["turnover_bucket"].eq(bucket)]
        summaries.append(
            {
                "bucket": bucket,
                "experiment_count": int(len(values)),
                "median_turnover": float(values["full_turnover"].median()),
                "median_validation_return": float(
                    values["validation_return"].median()
                ),
                "median_locked_return": float(
                    values["locked_return"].median()
                ),
                "median_return_decay": float(
                    values["return_decay"].median()
                ),
                "locked_positive_ratio": float(
                    values["locked_return"].gt(0).mean()
                ),
                "locked_core_pass_count": int(
                    values["locked_core_pass"].sum()
                ),
            }
        )
    summary = pd.DataFrame(summaries)
    indexed = summary.set_index("bucket")
    low = indexed.loc["low_le_8x"]
    high = indexed.loc["high_gt_15x"]
    low_return_advantage = float(
        low["median_locked_return"] - high["median_locked_return"]
    )
    checks = {
        "source_has_at_least_30_experiments": len(frame) >= 30,
        "all_turnover_buckets_nonempty": bool(
            summary["experiment_count"].gt(0).all()
        ),
        "low_locked_return_advantage_at_least_3pct": (
            bool(low_return_advantage >= 0.03)
        ),
        "low_positive_ratio_exceeds_high": (
            bool(
                low["locked_positive_ratio"]
                > high["locked_positive_ratio"]
            )
        ),
    }
    no_bucket_passes = bool(
        summary["locked_core_pass_count"].eq(0).all()
    )
    turnover_locked_spearman = float(
        frame["full_turnover"].rank().corr(
            frame["locked_return"].rank()
        )
    )
    if (
        checks["low_locked_return_advantage_at_least_3pct"]
        and checks["low_positive_ratio_exceeds_high"]
        and no_bucket_passes
    ):
        classification = "LOWER_TURNOVER_HELPS_BUT_IS_NOT_SUFFICIENT"
    elif no_bucket_passes:
        classification = "NO_TURNOVER_BUCKET_SURVIVES_LOCKED_GATE"
    else:
        classification = "INCONCLUSIVE"
    result = {
        "source_experiment_count": int(len(frame)),
        "bucket_summaries": summary.to_dict("records"),
        "turnover_locked_return_spearman": turnover_locked_spearman,
        "low_minus_high_median_locked_return": low_return_advantage,
        "checks": checks,
        "no_bucket_has_locked_core_pass": no_bucket_passes,
        "classification": classification,
        "source_decisions_overridden": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, frame


def classify_turnover(value: float) -> str:
    turnover = float(value)
    if turnover <= 8.0:
        return "low_le_8x"
    if turnover <= 15.0:
        return "medium_8_to_15x"
    return "high_gt_15x"


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    classified: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    rows_path = attempt.output_dir / "classified_experiments.csv"
    classified.to_csv(rows_path, index=False)
    metrics_path = attempt.output_dir / "turnover_regime_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "低换手改善锁定期分布，但所有换手层均无策略通过锁定核心门槛"
            if result["classification"].startswith("LOWER_")
            else "换手分层本身不能解释或解决锁定期失效"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "换手分层报告"),
            ExperimentArtifact("classified", rows_path, "因子分层明细"),
            ExperimentArtifact("metrics", metrics_path, "分层指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {item['bucket']} | {item['experiment_count']} | "
        f"{item['median_turnover']:.2f}x | "
        f"{item['median_validation_return']:.2%} | "
        f"{item['median_locked_return']:.2%} | "
        f"{item['locked_positive_ratio']:.1%} | "
        f"{item['locked_core_pass_count']} |"
        for item in result["bucket_summaries"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# A股因子换手分层锁定期存活审计 V1

- 来源家族：{result['source_experiment_count']}。
- 分类：{result['classification']}。
- 换手与锁定收益Spearman：
  {result['turnover_locked_return_spearman']:.3f}。
- 低换手减高换手的锁定收益中位差：
  {result['low_minus_high_median_locked_return']:.2%}。

| 换手层 | 家族数 | 换手中位 | 验证收益中位 | 锁定收益中位 | 锁定正收益 | 锁定过门槛 |
|---|---:|---:|---:|---:|---:|---:|
{rows}

## 描述性门槛

{checks}

低换手若有优势也只代表摩擦和稳定性改善，不构成Alpha来源；本审计不重新
分类任何源策略，也不把低频本身当作晋级理由。
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
