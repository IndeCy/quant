"""低换手与高换手因子锁定收益差的Bootstrap与置换审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import a_share_factor_turnover_regime_audit as source
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


EXPERIMENT_ID = "a_share_factor_turnover_statistical_audit_v1"
REPORT_PATH = Path(
    "docs/research/a-share-factor-turnover-statistical-audit-v1.md"
)
SAMPLES = 10_000
SEED = 20260729
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="A股因子低换手优势统计审计 V1",
    category="research_governance",
    hypothesis=(
        "低换手组相对高换手组9个百分点的锁定收益中位优势，是否在家族级"
        "Bootstrap和标签置换中具有足够稳定性"
    ),
    definition={
        "source_turnover_audit": source.EXPERIMENT_ID,
        "comparison": "low_le_8x_minus_high_gt_15x_locked_return",
        "bootstrap": {
            "samples": SAMPLES,
            "resample_within_group": True,
            "seed": SEED,
        },
        "permutation": {
            "samples": SAMPLES,
            "statistic": "median_difference",
            "alternative": "low_greater_than_high",
            "seed": SEED,
        },
        "frozen_gate": {
            "probability_positive_difference_min": 0.80,
            "probability_difference_at_least_3pct_min": 0.70,
            "one_sided_permutation_pvalue_max": 0.10,
            "bootstrap_difference_p05_floor": -0.03,
        },
        "descriptive_family_level_inference": True,
        "does_not_establish_alpha": True,
        "does_not_override_source_decisions": True,
        "promotion_scope": "meta_statistical_evidence_only",
        "methodology_version": "family_bootstrap_permutation_v1",
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
        require_source_conclusion(paths)
        rows = source.load_source_rows(paths)
        result, bootstrap, permutation = calculate(rows, paths)
        complete_attempt(attempt, result, bootstrap, permutation)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    rows: list[dict[str, Any]],
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    frame = pd.DataFrame(rows).copy()
    frame["turnover_bucket"] = frame["full_turnover"].map(
        source.classify_turnover
    )
    low = frame.loc[
        frame["turnover_bucket"].eq("low_le_8x"), "locked_return"
    ].to_numpy(dtype=float)
    high = frame.loc[
        frame["turnover_bucket"].eq("high_gt_15x"), "locked_return"
    ].to_numpy(dtype=float)
    if len(low) < 8 or len(high) < 8:
        raise ValueError("低换手或高换手家族不足8个")
    original = float(np.median(low) - np.median(high))
    bootstrap = bootstrap_median_difference(
        low,
        high,
        samples=SAMPLES,
        seed=SEED,
    )
    permutation = permutation_median_difference(
        low,
        high,
        samples=SAMPLES,
        seed=SEED,
    )
    probability_positive = float(
        bootstrap["median_difference"].gt(0).mean()
    )
    probability_three = float(
        bootstrap["median_difference"].ge(0.03).mean()
    )
    pvalue = float(
        (1 + permutation["median_difference"].ge(original).sum())
        / (1 + len(permutation))
    )
    distribution = {
        "p05": float(bootstrap["median_difference"].quantile(0.05)),
        "median": float(bootstrap["median_difference"].median()),
        "p95": float(bootstrap["median_difference"].quantile(0.95)),
    }
    checks = {
        "probability_positive_difference_at_least_80pct": (
            probability_positive >= 0.80
        ),
        "probability_difference_at_least_3pct_at_least_70pct": (
            probability_three >= 0.70
        ),
        "one_sided_permutation_pvalue_within_10pct": pvalue <= 0.10,
        "bootstrap_difference_p05_above_minus_3pct": (
            distribution["p05"] >= -0.03
        ),
    }
    passed = all(checks.values())
    result = {
        "low_family_count": int(len(low)),
        "high_family_count": int(len(high)),
        "original_median_difference": original,
        "bootstrap": {
            "samples": SAMPLES,
            "probability_positive_difference": probability_positive,
            "probability_difference_at_least_3pct": probability_three,
            "distribution": distribution,
        },
        "permutation": {
            "samples": SAMPLES,
            "one_sided_pvalue": pvalue,
        },
        "checks": checks,
        "classification": (
            "LOWER_TURNOVER_ADVANTAGE_STATISTICALLY_SUPPORTED"
            if passed
            else "INCONCLUSIVE"
        ),
        "establishes_alpha": False,
        "source_decisions_overridden": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, bootstrap, permutation


def bootstrap_median_difference(
    low: np.ndarray,
    high: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    low_indices = rng.integers(0, len(low), size=(samples, len(low)))
    high_indices = rng.integers(0, len(high), size=(samples, len(high)))
    differences = (
        np.median(low[low_indices], axis=1)
        - np.median(high[high_indices], axis=1)
    )
    return pd.DataFrame({"median_difference": differences})


def permutation_median_difference(
    low: np.ndarray,
    high: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    combined = np.concatenate([low, high])
    differences = np.empty(samples, dtype=float)
    for index in range(samples):
        shuffled = rng.permutation(combined)
        differences[index] = (
            np.median(shuffled[: len(low)])
            - np.median(shuffled[len(low) :])
        )
    return pd.DataFrame({"median_difference": differences})


def require_source_conclusion(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("换手分层审计依赖尚未成功")
    if latest.get("outcome") != "LOWER_TURNOVER_HELPS_BUT_IS_NOT_SUFFICIENT":
        raise RuntimeError(
            f"换手分层结论不符: {latest.get('outcome')}"
        )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    bootstrap: pd.DataFrame,
    permutation: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    bootstrap_path = attempt.output_dir / "bootstrap_samples.csv"
    bootstrap.to_csv(bootstrap_path, index=False)
    permutation_path = attempt.output_dir / "permutation_samples.csv"
    permutation.to_csv(permutation_path, index=False)
    metrics_path = attempt.output_dir / "statistical_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "低换手相对高换手的锁定收益分布优势通过家族级统计门槛"
            if result["classification"].endswith("SUPPORTED")
            else "家族样本不足以稳健确认低换手分布优势"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "换手统计审计报告"),
            ExperimentArtifact("bootstrap", bootstrap_path, "Bootstrap样本"),
            ExperimentArtifact("permutation", permutation_path, "置换样本"),
            ExperimentArtifact("metrics", metrics_path, "统计审计指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    bootstrap = result["bootstrap"]
    distribution = bootstrap["distribution"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# A股因子低换手优势统计审计 V1

- 低/高换手家族：{result['low_family_count']} /
  {result['high_family_count']}。
- 原始锁定收益中位差：{result['original_median_difference']:.2%}。
- Bootstrap差值为正概率：
  {bootstrap['probability_positive_difference']:.2%}。
- Bootstrap差值至少3个百分点概率：
  {bootstrap['probability_difference_at_least_3pct']:.2%}。
- 差值P05/中位/P95：{distribution['p05']:.2%} /
  {distribution['median']:.2%} / {distribution['p95']:.2%}。
- 单侧置换p值：{result['permutation']['one_sided_pvalue']:.4f}。
- 分类：{result['classification']}。

## 冻结门槛

{checks}

这只是31个研究家族之间的描述性推断。即使低换手分布更好，也不代表低频
策略产生Alpha；所有换手层的锁定核心通过数仍为0。
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
