"""标普黄金12%波动目标相对同机制标普的统计优势审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq_gold_sp500_statistical_dominance_audit as stats
from examples import sp500_gold_vol_target_failure_attribution_audit as failure
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


EXPERIMENT_ID = "sp500_gold_vol_target_statistical_audit_v1"
REPORT_PATH = Path(
    "docs/research/sp500-gold-vol-target-statistical-audit-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="标普黄金波动目标统计优势 V1",
    category="robustness",
    hypothesis=(
        "标普黄金60/40风险块相对使用相同12%波动目标机制的纯标普，收益、"
        "Sharpe与回撤优势是否经配对区块Bootstrap及滚动三年仍稳定"
    ),
    definition={
        "source_strategy": source.EXPERIMENT_ID,
        "source_failure_attribution": failure.EXPERIMENT_ID,
        "candidate": source.EXPERIMENT_ID,
        "control": source.VOL_CONTROL_ID,
        "sample": {"start": source.OOS_START, "end": "LATEST"},
        "bootstrap": {
            "paired": True,
            "block_days": stats.BLOCK_DAYS,
            "samples": stats.BOOTSTRAP_SAMPLES,
            "seed": stats.SEED,
        },
        "rolling": {
            "window_days": stats.ROLLING_DAYS,
            "step_days": stats.ROLLING_STEP,
        },
        "frozen_gate": {
            "probability_return_lift_at_least_1pct_min": 0.80,
            "probability_sharpe_lift_at_least_010_min": 0.80,
            "probability_drawdown_improvement_positive_min": 0.80,
            "bootstrap_return_lift_p05_floor": -0.01,
            "rolling_positive_return_lift_share_min": 0.70,
            "rolling_positive_sharpe_lift_share_min": 0.70,
        },
        "does_not_override_source_rejection": True,
        "does_not_change_parameters": True,
        "promotion_scope": "statistical_audit_only",
        "methodology_version": "paired_block_same_vol_control_v1",
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
        require_dependencies(paths)
        returns, source_path = load_returns(paths)
        result, samples, rolling = calculate(returns, source_path, paths)
        complete_attempt(attempt, result, samples, rolling)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def load_returns(paths: RuntimePaths) -> tuple[pd.DataFrame, str]:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest:
        raise RuntimeError("缺少标普黄金波动目标运行记录")
    artifact = next(
        (
            item
            for item in latest.get("artifacts") or []
            if item.get("artifact_type") == "daily_nav"
        ),
        None,
    )
    if artifact is None:
        raise RuntimeError("标普黄金波动目标缺少每日净值产物")
    path = Path(str(artifact["file_path"]))
    if not path.exists():
        path = (
            paths.root
            / "runs"
            / "experiments"
            / source.EXPERIMENT_ID
            / Path(str(latest["output_dir"])).name
            / path.name
        )
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.set_index("trade_date").sort_index()
    required = [source.EXPERIMENT_ID, source.VOL_CONTROL_ID]
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"每日净值缺少列: {missing}")
    returns = (
        frame[required]
        .pct_change(fill_method=None)
        .loc[source.OOS_START:]
        .dropna()
    )
    returns.columns = ["candidate", "sp500"]
    if len(returns) < 1500:
        raise ValueError("统计审计共同收益不足1500日")
    return returns, str(path)


def calculate(
    returns: pd.DataFrame,
    source_path: str,
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    original = stats.compare_metrics(
        returns["candidate"].to_numpy(),
        returns["sp500"].to_numpy(),
    )
    samples = stats.paired_block_bootstrap(
        returns,
        samples=stats.BOOTSTRAP_SAMPLES,
        block_days=stats.BLOCK_DAYS,
        seed=stats.SEED,
    )
    rolling = stats.rolling_comparisons(
        returns,
        window_days=stats.ROLLING_DAYS,
        step_days=stats.ROLLING_STEP,
    )
    probabilities = {
        "return_lift_at_least_1pct": float(
            samples["return_lift"].ge(0.01).mean()
        ),
        "sharpe_lift_at_least_010": float(
            samples["sharpe_lift"].ge(0.10).mean()
        ),
        "drawdown_improvement_positive": float(
            samples["drawdown_improvement"].gt(0.0).mean()
        ),
    }
    distributions = {
        column: {
            "p05": float(samples[column].quantile(0.05)),
            "median": float(samples[column].median()),
            "p95": float(samples[column].quantile(0.95)),
        }
        for column in (
            "return_lift",
            "sharpe_lift",
            "drawdown_improvement",
        )
    }
    rolling_summary = {
        "windows": int(len(rolling)),
        "positive_return_lift_share": float(
            rolling["return_lift"].gt(0).mean()
        ),
        "positive_sharpe_lift_share": float(
            rolling["sharpe_lift"].gt(0).mean()
        ),
        "positive_drawdown_improvement_share": float(
            rolling["drawdown_improvement"].gt(0).mean()
        ),
        "return_lift_p10": float(rolling["return_lift"].quantile(0.10)),
        "return_lift_median": float(rolling["return_lift"].median()),
        "return_lift_p90": float(rolling["return_lift"].quantile(0.90)),
    }
    checks = {
        "return_lift_probability_at_least_80pct": (
            probabilities["return_lift_at_least_1pct"] >= 0.80
        ),
        "sharpe_lift_probability_at_least_80pct": (
            probabilities["sharpe_lift_at_least_010"] >= 0.80
        ),
        "drawdown_improvement_probability_at_least_80pct": (
            probabilities["drawdown_improvement_positive"] >= 0.80
        ),
        "bootstrap_return_lift_p05_above_minus_1pct": (
            distributions["return_lift"]["p05"] >= -0.01
        ),
        "rolling_positive_return_lift_share_at_least_70pct": (
            rolling_summary["positive_return_lift_share"] >= 0.70
        ),
        "rolling_positive_sharpe_lift_share_at_least_70pct": (
            rolling_summary["positive_sharpe_lift_share"] >= 0.70
        ),
    }
    probability_values = list(probabilities.values())
    if all(checks.values()):
        classification = "ROBUST_STATISTICAL_PASS_SOURCE_STILL_REJECTED"
    elif any(value < 0.50 for value in probability_values):
        classification = "ROBUST_STATISTICAL_FAIL"
    else:
        classification = "INCONCLUSIVE"
    return {
        "source_nav_path": source_path,
        "common_return_days": int(len(returns)),
        "original": original,
        "bootstrap": {
            "samples": stats.BOOTSTRAP_SAMPLES,
            "block_days": stats.BLOCK_DAYS,
            "probabilities": probabilities,
            "distributions": distributions,
        },
        "rolling_756d": rolling_summary,
        "checks": checks,
        "classification": classification,
        "source_rejection_overridden": False,
        "strategy_promoted": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }, samples, rolling


def require_dependencies(paths: RuntimePaths) -> None:
    expected = {
        source.EXPERIMENT_ID: "REJECTED",
        failure.EXPERIMENT_ID: "CONCENTRATED_BORDERLINE_REJECTION",
    }
    repository = SystemRepository(paths.system_state_path)
    for experiment_id, outcome in expected.items():
        detail = repository.load_experiment_detail(experiment_id)
        latest = detail.get("latest_run") if detail else None
        if not latest or latest.get("status") != "SUCCESS":
            raise RuntimeError(f"依赖未成功: {experiment_id}")
        if latest.get("outcome") != outcome:
            raise RuntimeError(
                f"依赖结论不符: {experiment_id}={latest.get('outcome')}"
            )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    samples: pd.DataFrame,
    rolling: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    samples_path = attempt.output_dir / "bootstrap_samples.csv"
    samples.to_csv(samples_path, index=False)
    rolling_path = attempt.output_dir / "rolling_756d_windows.csv"
    rolling.to_csv(rolling_path, index=False)
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
            "同风险预算优势具统计稳健性，但原冻结门槛拒绝保持"
            if result["classification"].startswith("ROBUST_STATISTICAL_PASS")
            else "统计审计不足以支持同风险预算稳定优势，原拒绝保持"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "统计审计报告"),
            ExperimentArtifact("bootstrap", samples_path, "Bootstrap样本"),
            ExperimentArtifact("rolling", rolling_path, "滚动三年窗口"),
            ExperimentArtifact("metrics", metrics_path, "统计审计指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    original = result["original"]
    probabilities = result["bootstrap"]["probabilities"]
    distributions = result["bootstrap"]["distributions"]
    rolling = result["rolling_756d"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 标普黄金波动目标统计优势 V1

- 共同日收益：{result['common_return_days']}；配对20日区块Bootstrap：
  {result['bootstrap']['samples']}次。
- 对照为相同12%波动目标机制的纯标普，不是直接满仓标普。
- 原样本年化收益提升：{original['return_lift']:.2%}；
  Sharpe提升：{original['sharpe_lift']:.3f}；
  回撤改善：{original['drawdown_improvement']:.2%}。
- P(收益提升≥1%)：{probabilities['return_lift_at_least_1pct']:.1%}；
  P(Sharpe提升≥0.10)：
  {probabilities['sharpe_lift_at_least_010']:.1%}；
  P(回撤改善>0)：
  {probabilities['drawdown_improvement_positive']:.1%}。
- 收益提升Bootstrap P05/中位/P95：
  {distributions['return_lift']['p05']:.2%} /
  {distributions['return_lift']['median']:.2%} /
  {distributions['return_lift']['p95']:.2%}。
- 滚动三年收益/Sharpe提升为正占比：
  {rolling['positive_return_lift_share']:.1%} /
  {rolling['positive_sharpe_lift_share']:.1%}。
- 分类：`{result['classification']}`。

## 冻结门槛

{checks}

统计通过也不覆盖来源策略的冻结拒绝，不修改参数，不构成生产晋级。
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
