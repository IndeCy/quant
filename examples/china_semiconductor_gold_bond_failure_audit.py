"""半导体黄金国债相对全球防守的冻结失败统计审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import china_semiconductor_gold_bond_study as base
from examples import nasdaq_gold_sp500_statistical_dominance_audit as statistics
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


EXPERIMENT_ID = "china_semiconductor_gold_bond_failure_audit_v1"
REPORT_PATH = Path(
    "docs/research/china-semiconductor-gold-bond-failure-audit-v1.md"
)
SAMPLES = 10_000
BLOCK_DAYS = 20
SEED = 20260729
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="半导体黄金国债失败统计审计 V1",
    category="robustness",
    hypothesis=(
        "三等权候选相对全球防守的Sharpe短缺是否为稳定失败，还是短样本噪声"
    ),
    definition={
        "source_strategy": base.EXPERIMENT_ID,
        "required_source_outcome": "REJECTED",
        "original_failed_checks_required": [
            "sharpe_shortfall_vs_global_within_010",
            "all_three_folds_positive",
        ],
        "bootstrap": {
            "paired": True,
            "block_days": BLOCK_DAYS,
            "samples": SAMPLES,
            "seed": SEED,
        },
        "frozen_probabilities": {
            "sharpe_lift_at_least_minus_010": 0.80,
            "return_lift_at_least_minus_002": 0.80,
            "drawdown_improvement_positive": 0.50,
        },
        "robust_failure": (
            "probability_sharpe_lift_at_least_minus_010_below_20pct"
        ),
        "original_gate_override": False,
        "promotion_scope": "failure_audit_only",
        "methodology_version": "paired_block_failure_audit_v1",
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
        returns, source_path = load_returns_and_require_failure(paths)
        result, samples = calculate(returns, source_path)
        complete_attempt(attempt, result, samples)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def load_returns_and_require_failure(
    paths: RuntimePaths,
) -> tuple[pd.DataFrame, str]:
    repository = SystemRepository(paths.system_state_path)
    detail = repository.load_experiment_detail(base.EXPERIMENT_ID)
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("半导体三资产研究尚未成功完成")
    if latest.get("outcome") != "REJECTED":
        raise RuntimeError("半导体三资产必须保持拒绝结论")
    metrics = latest.get("metrics") or {}
    checks = (metrics.get("gate") or {}).get("checks") or {}
    failed = sorted(name for name, passed in checks.items() if not passed)
    expected = sorted(
        RESEARCH_SPEC.definition["original_failed_checks_required"]
    )
    if failed != expected:
        raise RuntimeError(f"源研究失败集合已变化: {failed}")
    artifact = next(
        (
            item
            for item in (latest.get("artifacts") or [])
            if item.get("artifact_type") == "daily_nav"
        ),
        None,
    )
    if artifact is None:
        raise RuntimeError("半导体三资产缺少每日净值")
    path = Path(str(artifact["file_path"]))
    if not path.exists():
        path = (
            paths.root
            / "runs"
            / "experiments"
            / base.EXPERIMENT_ID
            / Path(str(latest["output_dir"])).name
            / path.name
        )
    frame = pd.read_csv(path)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.set_index("trade_date").sort_index()
    required = [base.EXPERIMENT_ID, base.GLOBAL_ID]
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"净值对照缺少列: {missing}")
    returns = (
        frame[required]
        .pct_change(fill_method=None)
        .loc[base.STUDY_START:]
        .dropna()
    )
    returns.columns = ["candidate", "sp500"]
    if len(returns) < 1500:
        raise ValueError("失败统计审计共同日收益不足1500")
    return returns, str(path)


def calculate(
    returns: pd.DataFrame,
    source_path: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    original = statistics.compare_metrics(
        returns["candidate"].to_numpy(),
        returns["sp500"].to_numpy(),
    )
    samples = statistics.paired_block_bootstrap(
        returns,
        samples=SAMPLES,
        block_days=BLOCK_DAYS,
        seed=SEED,
    )
    probabilities = {
        "sharpe_lift_at_least_minus_010": float(
            samples["sharpe_lift"].ge(-0.10).mean()
        ),
        "return_lift_at_least_minus_002": float(
            samples["return_lift"].ge(-0.02).mean()
        ),
        "drawdown_improvement_positive": float(
            samples["drawdown_improvement"].gt(0).mean()
        ),
    }
    distributions = {
        column: {
            "p05": float(samples[column].quantile(0.05)),
            "median": float(samples[column].median()),
            "p95": float(samples[column].quantile(0.95)),
        }
        for column in [
            "return_lift",
            "sharpe_lift",
            "drawdown_improvement",
        ]
    }
    checks = {
        "sharpe_tolerance_probability_at_least_80pct": (
            probabilities["sharpe_lift_at_least_minus_010"] >= 0.80
        ),
        "return_tolerance_probability_at_least_80pct": (
            probabilities["return_lift_at_least_minus_002"] >= 0.80
        ),
        "drawdown_improvement_probability_at_least_50pct": (
            probabilities["drawdown_improvement_positive"] >= 0.50
        ),
    }
    sharpe_probability = probabilities["sharpe_lift_at_least_minus_010"]
    if all(checks.values()):
        classification = "ROBUST_FAILURE_NOT_CONFIRMED"
    elif sharpe_probability < 0.20:
        classification = "ROBUST_SHARPE_FAILURE"
    else:
        classification = "INCONCLUSIVE"
    result = {
        "source_nav_path": source_path,
        "common_return_days": int(len(returns)),
        "original": original,
        "bootstrap": {
            "samples": SAMPLES,
            "block_days": BLOCK_DAYS,
            "probabilities": probabilities,
            "distributions": distributions,
        },
        "checks": checks,
        "classification": classification,
        "original_gate_overridden": False,
        "report_path": "",
        "reused": False,
    }
    return result, samples


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    samples: pd.DataFrame,
) -> None:
    result["report_path"] = str(attempt.paths.root / REPORT_PATH)
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    samples_path = attempt.output_dir / "bootstrap_samples.csv"
    samples.to_csv(samples_path, index=False)
    metrics_path = attempt.output_dir / "failure_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=result["classification"],
        decision_reason=(
            "配对Bootstrap确认Sharpe相对全球防守为稳健失败"
            if result["classification"] == "ROBUST_SHARPE_FAILURE"
            else "统计证据不足以改变或确认原失败，原门槛保持"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "失败统计审计报告"),
            ExperimentArtifact("bootstrap", samples_path, "Bootstrap样本"),
            ExperimentArtifact("metrics", metrics_path, "失败概率指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    original = result["original"]
    probabilities = result["bootstrap"]["probabilities"]
    distributions = result["bootstrap"]["distributions"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 半导体黄金国债失败统计审计 V1

- 候选与同区间全球防守日收益配对，20日区块Bootstrap
  {result['bootstrap']['samples']}次。
- 原研究的失败门槛不覆盖，不生成权重变体。

## 原样本相对全球防守

- 年化收益差：{original['return_lift']:.2%}
- Sharpe差：{original['sharpe_lift']:.3f}
- 最大回撤改善：{original['drawdown_improvement']:.2%}

## Bootstrap

- P(Sharpe差≥-0.10)：
  {probabilities['sharpe_lift_at_least_minus_010']:.1%}
- P(年化收益差≥-2%)：
  {probabilities['return_lift_at_least_minus_002']:.1%}
- P(回撤改善>0)：
  {probabilities['drawdown_improvement_positive']:.1%}
- Sharpe差 P05/中位/P95：
  {distributions['sharpe_lift']['p05']:.3f} /
  {distributions['sharpe_lift']['median']:.3f} /
  {distributions['sharpe_lift']['p95']:.3f}

## 冻结判定

{checks}

结论：`{result['classification']}`。原候选继续保持拒绝状态。
"""


def data_version(paths: RuntimePaths) -> str:
    stat = paths.system_state_path.stat()
    return f"system_state:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260728")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
