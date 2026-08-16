"""90/10融资流卫星组合与Quality边界相关性的区块抽样审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import global_defensive_margin_flow_satellite_study as base
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


EXPERIMENT_ID = "global_defensive_margin_flow_correlation_audit_v1"
REPORT_PATH = Path(
    "docs/research/global-defensive-margin-flow-correlation-audit-v1.md"
)
THRESHOLD = 0.40
SAMPLES = 10000
BLOCK_DAYS = 20
SEED = 20260729

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="90/10融资流组合边界相关性审计 V1",
    category="correlation_robustness",
    hypothesis=(
        "90/10融资流组合与Quality的0.431日收益相关是否在滚动窗口、残差相关和20日"
        "区块bootstrap下稳定高于0.40，而非有限样本噪声"
    ),
    definition={
        "dependency": base.EXPERIMENT_ID,
        "threshold": THRESHOLD,
        "statistics": [
            "pearson",
            "spearman",
            "benchmark_residual_pearson",
            "rolling_252d_pearson",
            "paired_20d_block_bootstrap",
        ],
        "bootstrap": {
            "samples": SAMPLES,
            "block_days": BLOCK_DAYS,
            "seed": SEED,
        },
        "classification": {
            "robust_failure_if_probability_above_threshold_min": 0.80,
            "robust_pass_if_p95_at_most_threshold": True,
            "otherwise": "INCONCLUSIVE",
        },
        "override_original_gate": False,
        "promotion_scope": "audit_only_no_registration",
        "methodology_version": "paired_return_correlation_blocks_v1",
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
        require_candidate_rejected_only_for_correlation(paths)
        result, aligned, bootstrap = calculate(paths, as_of_date)
        complete_attempt(attempt, result, aligned, bootstrap)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    candidate = load_candidate_artifact(paths)
    quality = load_quality(paths, as_of_date)
    aligned = align_returns(candidate, quality)
    pearson = float(aligned["candidate"].corr(aligned["quality"]))
    spearman = float(
        aligned["candidate"].corr(aligned["quality"], method="spearman")
    )
    residual = residual_correlation(aligned)
    rolling = (
        aligned["candidate"]
        .rolling(252)
        .corr(aligned["quality"])
        .dropna()
    )
    bootstrap = block_bootstrap_correlations(
        aligned[["candidate", "quality"]],
        samples=SAMPLES,
        block_days=BLOCK_DAYS,
        seed=SEED,
    )
    p05 = float(bootstrap["correlation"].quantile(0.05))
    p95 = float(bootstrap["correlation"].quantile(0.95))
    probability = float(bootstrap["correlation"].gt(THRESHOLD).mean())
    if probability >= 0.80:
        classification = "ROBUST_CORRELATION_FAILURE"
    elif p95 <= THRESHOLD:
        classification = "ROBUST_CORRELATION_PASS"
    else:
        classification = "INCONCLUSIVE"
    result = {
        "experiment_id": EXPERIMENT_ID,
        "common_returns": len(aligned),
        "pearson": pearson,
        "spearman": spearman,
        "benchmark_residual_correlation": residual,
        "rolling_252d": {
            "windows": len(rolling),
            "median": float(rolling.median()),
            "p10": float(rolling.quantile(0.10)),
            "p90": float(rolling.quantile(0.90)),
            "share_above_threshold": float(rolling.gt(THRESHOLD).mean()),
        },
        "bootstrap": {
            "samples": len(bootstrap),
            "p05": p05,
            "median": float(bootstrap["correlation"].median()),
            "p95": p95,
            "probability_above_threshold": probability,
        },
        "classification": classification,
        "original_gate_overridden": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, aligned, bootstrap


def align_returns(
    candidate: pd.DataFrame,
    quality: pd.DataFrame,
) -> pd.DataFrame:
    left = candidate[
        ["trade_date", "portfolio_nav", "benchmark_nav"]
    ].copy()
    left["candidate"] = left["portfolio_nav"].astype(float).pct_change()
    left["benchmark"] = left["benchmark_nav"].astype(float).pct_change()
    right = quality[["trade_date", "nav"]].copy()
    right["quality"] = right["nav"].astype(float).pct_change()
    return left.merge(
        right[["trade_date", "quality"]],
        on="trade_date",
        how="inner",
        validate="one_to_one",
    ).dropna()[["trade_date", "candidate", "quality", "benchmark"]]


def residual_correlation(aligned: pd.DataFrame) -> float:
    benchmark = aligned["benchmark"].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(benchmark)), benchmark])
    candidate = aligned["candidate"].to_numpy(dtype=float)
    quality = aligned["quality"].to_numpy(dtype=float)
    candidate_residual = candidate - design @ np.linalg.lstsq(
        design,
        candidate,
        rcond=None,
    )[0]
    quality_residual = quality - design @ np.linalg.lstsq(
        design,
        quality,
        rcond=None,
    )[0]
    return float(np.corrcoef(candidate_residual, quality_residual)[0, 1])


def block_bootstrap_correlations(
    returns: pd.DataFrame,
    *,
    samples: int,
    block_days: int,
    seed: int,
) -> pd.DataFrame:
    values = returns[["candidate", "quality"]].to_numpy(dtype=float)
    n = len(values)
    if n < block_days * 2:
        raise ValueError("insufficient returns for correlation bootstrap")
    rng = np.random.default_rng(seed)
    blocks_needed = int(np.ceil(n / block_days))
    max_start = n - block_days
    rows = []
    for _ in range(samples):
        starts = rng.integers(0, max_start + 1, size=blocks_needed)
        indexes = np.concatenate(
            [np.arange(start, start + block_days) for start in starts]
        )[:n]
        sample = values[indexes]
        rows.append(
            float(np.corrcoef(sample[:, 0], sample[:, 1])[0, 1])
        )
    return pd.DataFrame({"correlation": rows})


def load_candidate_artifact(paths: RuntimePaths) -> pd.DataFrame:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        base.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest:
        raise RuntimeError("90/10组合实验不存在")
    path = Path(str(latest["output_dir"])) / "daily_nav.csv"
    return pd.read_csv(path, dtype={"trade_date": str})


def load_quality(paths: RuntimePaths, as_of_date: str) -> pd.DataFrame:
    uri = f"file:{paths.monitoring_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        return pd.read_sql_query(
            """
            SELECT trade_date, nav
            FROM strategy_nav_daily
            WHERE strategy_id = ? AND trade_date <= ?
            ORDER BY trade_date
            """,
            connection,
            params=[base.QUALITY_ID, as_of_date],
        )


def require_candidate_rejected_only_for_correlation(paths: RuntimePaths) -> None:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        base.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("outcome") != "REJECTED":
        raise RuntimeError("90/10组合不是可审计的REJECTED结果")
    checks = latest.get("metrics", {}).get("gate", {}).get("checks", {})
    failed = [name for name, value in checks.items() if not value]
    if failed != ["quality_correlation_at_most_040"]:
        raise RuntimeError(f"90/10组合并非仅相关性失败: {failed}")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    aligned: pd.DataFrame,
    bootstrap: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    aligned_path = attempt.output_dir / "aligned_returns.csv"
    aligned.to_csv(aligned_path, index=False)
    bootstrap_path = attempt.output_dir / "bootstrap_correlations.csv"
    bootstrap.to_csv(bootstrap_path, index=False)
    metrics_path = attempt.output_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=result["classification"],
        decision_reason=(
            f"边界相关性分类为{result['classification']}；原冻结门槛不被覆盖"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "边界相关性审计报告"),
            ExperimentArtifact("aligned_returns", aligned_path, "共同日收益"),
            ExperimentArtifact("bootstrap", bootstrap_path, "区块抽样相关"),
            ExperimentArtifact("metrics", metrics_path, "审计指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rolling = result["rolling_252d"]
    bootstrap = result["bootstrap"]
    return f"""# 90/10融资流组合与Quality边界相关性审计 V1

- 共同日收益：{result['common_returns']}
- Pearson/Spearman：{result['pearson']:.4f} / {result['spearman']:.4f}
- 剔除沪深300线性Beta后残差相关：{result['benchmark_residual_correlation']:.4f}
- 252日滚动相关 P10/中位/P90：{rolling['p10']:.4f} /
  {rolling['median']:.4f} / {rolling['p90']:.4f}；
  高于0.40占比 {rolling['share_above_threshold']:.2%}。
- 20日区块bootstrap P05/中位/P95：{bootstrap['p05']:.4f} /
  {bootstrap['median']:.4f} / {bootstrap['p95']:.4f}；
  高于0.40概率 {bootstrap['probability_above_threshold']:.2%}。

结论：`{result['classification']}`。原相关性门槛不覆盖，组合仍保持拒绝状态。
"""


def _data_version(paths: RuntimePaths) -> str:
    stat = paths.monitoring_path.stat()
    return f"monitoring:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260723")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
