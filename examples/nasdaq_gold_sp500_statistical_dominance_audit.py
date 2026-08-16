"""纳指黄金60/40相对标普500的配对区块Bootstrap统计稳健性审计。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq_gold_sp500_hurdle_robustness_study as robustness
from examples import nasdaq_gold_sp500_hurdle_study as base
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


EXPERIMENT_ID = "nasdaq_gold_60_40_sp500_statistical_dominance_audit_v1"
REPORT_PATH = Path(
    "docs/research/nasdaq-gold-60-40-sp500-statistical-dominance-audit-v1.md"
)
BOOTSTRAP_SAMPLES = 10_000
BLOCK_DAYS = 20
SEED = 20260729
ROLLING_DAYS = 756
ROLLING_STEP = 21
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指黄金60/40相对标普统计支配审计 V1",
    category="robustness",
    hypothesis=(
        "已通过确定性压力矩阵的纳指黄金60/40，相对场内标普的收益、Sharpe和回撤"
        "优势是否在配对区块重采样及滚动三年窗口中仍有足够概率"
    ),
    definition={
        "source_strategy": base.EXPERIMENT_ID,
        "source_robustness": robustness.EXPERIMENT_ID,
        "sample": {"start": base.OOS_START, "end": "LATEST"},
        "bootstrap": {
            "paired": True,
            "block_days": BLOCK_DAYS,
            "samples": BOOTSTRAP_SAMPLES,
            "seed": SEED,
        },
        "rolling": {
            "window_days": ROLLING_DAYS,
            "step_days": ROLLING_STEP,
        },
        "frozen_gate": {
            "probability_return_lift_at_least_05pct_min": 0.80,
            "probability_sharpe_lift_at_least_005_min": 0.80,
            "probability_drawdown_improvement_positive_min": 0.80,
            "bootstrap_return_lift_p05_floor": -0.01,
            "rolling_positive_return_lift_share_min": 0.70,
            "rolling_positive_sharpe_lift_share_min": 0.70,
        },
        "classification": {
            "robust_pass": "all_frozen_checks",
            "robust_fail": "any_three_probability_checks_below_50pct",
            "otherwise": "inconclusive",
        },
        "does_not_override_source_gate": True,
        "promotion_scope": "statistical_audit_only",
        "methodology_version": "paired_block_bootstrap_v1",
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
        result, samples, rolling = calculate(returns, source_path)
        complete_attempt(attempt, result, samples, rolling)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def load_returns(
    paths: RuntimePaths,
) -> tuple[pd.DataFrame, str]:
    repository = SystemRepository(paths.system_state_path)
    detail = repository.load_experiment_detail(base.EXPERIMENT_ID)
    latest = detail.get("latest_run") if detail else None
    if not latest:
        raise RuntimeError("缺少纳指黄金V3运行记录")
    artifacts = latest.get("artifacts") or []
    nav_artifact = next(
        (
            item
            for item in artifacts
            if item.get("artifact_type") == "daily_nav"
        ),
        None,
    )
    if nav_artifact is None:
        raise RuntimeError("纳指黄金V3缺少每日净值产物")
    path = Path(str(nav_artifact["file_path"]))
    if not path.exists():
        candidate = (
            paths.root
            / "runs"
            / "experiments"
            / base.EXPERIMENT_ID
            / Path(str(latest["output_dir"])).name
            / path.name
        )
        path = candidate
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.set_index("trade_date").sort_index()
    required = [base.EXPERIMENT_ID, base.SP500_DIRECT_ID]
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"每日净值缺少列: {missing}")
    returns = (
        frame[required]
        .pct_change(fill_method=None)
        .loc[base.OOS_START:]
        .dropna()
    )
    returns.columns = ["candidate", "sp500"]
    if len(returns) < 1500:
        raise ValueError("统计审计共同收益不足1500日")
    return returns, str(path)


def calculate(
    returns: pd.DataFrame,
    source_path: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    original = compare_metrics(
        returns["candidate"].to_numpy(),
        returns["sp500"].to_numpy(),
    )
    samples = paired_block_bootstrap(
        returns,
        samples=BOOTSTRAP_SAMPLES,
        block_days=BLOCK_DAYS,
        seed=SEED,
    )
    rolling = rolling_comparisons(
        returns,
        window_days=ROLLING_DAYS,
        step_days=ROLLING_STEP,
    )
    probabilities = {
        "return_lift_at_least_05pct": float(
            samples["return_lift"].ge(0.005).mean()
        ),
        "sharpe_lift_at_least_005": float(
            samples["sharpe_lift"].ge(0.05).mean()
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
            probabilities["return_lift_at_least_05pct"] >= 0.80
        ),
        "sharpe_lift_probability_at_least_80pct": (
            probabilities["sharpe_lift_at_least_005"] >= 0.80
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
        classification = "ROBUST_STATISTICAL_PASS"
    elif any(value < 0.50 for value in probability_values):
        classification = "ROBUST_STATISTICAL_FAIL"
    else:
        classification = "INCONCLUSIVE"
    result = {
        "source_nav_path": source_path,
        "common_return_days": int(len(returns)),
        "original": original,
        "bootstrap": {
            "samples": BOOTSTRAP_SAMPLES,
            "block_days": BLOCK_DAYS,
            "probabilities": probabilities,
            "distributions": distributions,
        },
        "rolling_756d": rolling_summary,
        "checks": checks,
        "classification": classification,
        "source_gate_overridden": False,
        "report_path": "",
        "reused": False,
    }
    return result, samples, rolling


def compare_metrics(
    candidate_returns: np.ndarray,
    sp500_returns: np.ndarray,
) -> dict[str, float]:
    candidate = performance(candidate_returns)
    sp500 = performance(sp500_returns)
    return {
        "candidate_annualized_return": candidate["annualized_return"],
        "sp500_annualized_return": sp500["annualized_return"],
        "return_lift": (
            candidate["annualized_return"] - sp500["annualized_return"]
        ),
        "candidate_sharpe": candidate["sharpe"],
        "sp500_sharpe": sp500["sharpe"],
        "sharpe_lift": candidate["sharpe"] - sp500["sharpe"],
        "candidate_max_drawdown": candidate["max_drawdown"],
        "sp500_max_drawdown": sp500["max_drawdown"],
        "drawdown_improvement": (
            candidate["max_drawdown"] - sp500["max_drawdown"]
        ),
    }


def performance(returns: np.ndarray) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    nav = np.cumprod(1.0 + values)
    annualized = float(nav[-1] ** (252.0 / len(values)) - 1.0)
    volatility = float(values.std(ddof=1))
    sharpe = (
        float(values.mean() / volatility * math.sqrt(252))
        if volatility > 0
        else float("nan")
    )
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    return {
        "annualized_return": annualized,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
    }


def paired_block_bootstrap(
    returns: pd.DataFrame,
    *,
    samples: int,
    block_days: int,
    seed: int,
) -> pd.DataFrame:
    values = returns[["candidate", "sp500"]].to_numpy(dtype=float)
    n = len(values)
    blocks = int(math.ceil(n / block_days))
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(samples):
        starts = rng.integers(0, n - block_days + 1, size=blocks)
        indices = np.concatenate(
            [
                np.arange(start, start + block_days)
                for start in starts
            ]
        )[:n]
        sample = values[indices]
        rows.append(compare_metrics(sample[:, 0], sample[:, 1]))
    return pd.DataFrame(rows)


def rolling_comparisons(
    returns: pd.DataFrame,
    *,
    window_days: int,
    step_days: int,
) -> pd.DataFrame:
    rows = []
    for start in range(0, len(returns) - window_days + 1, step_days):
        window = returns.iloc[start : start + window_days]
        rows.append(
            {
                "start_date": window.index[0].strftime("%Y%m%d"),
                "end_date": window.index[-1].strftime("%Y%m%d"),
                **compare_metrics(
                    window["candidate"].to_numpy(),
                    window["sp500"].to_numpy(),
                ),
            }
        )
    if not rows:
        raise ValueError("滚动三年窗口为空")
    return pd.DataFrame(rows)


def require_dependencies(paths: RuntimePaths) -> None:
    repository = SystemRepository(paths.system_state_path)
    expected = {
        base.EXPERIMENT_ID: "PASSED_RESEARCH_GATE",
        robustness.EXPERIMENT_ID: "PASSED_RESEARCH_GATE",
    }
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
    result["report_path"] = str(attempt.paths.root / REPORT_PATH)
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    bootstrap_path = attempt.output_dir / "bootstrap_samples.csv"
    samples.to_csv(bootstrap_path, index=False)
    rolling_path = attempt.output_dir / "rolling_756d_windows.csv"
    rolling.to_csv(rolling_path, index=False)
    metrics_path = attempt.output_dir / "statistical_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    classification = result["classification"]
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=classification,
        decision_reason=(
            "配对区块Bootstrap与滚动窗口均支持统计支配"
            if classification == "ROBUST_STATISTICAL_PASS"
            else "统计审计不支持稳定支配，原历史门槛不覆盖"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "统计稳健性报告"),
            ExperimentArtifact("bootstrap", bootstrap_path, "Bootstrap样本"),
            ExperimentArtifact("rolling", rolling_path, "滚动三年窗口"),
            ExperimentArtifact("metrics", metrics_path, "统计指标"),
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
    return f"""# 纳指黄金60/40相对标普统计支配审计 V1

- 共同日收益：{result['common_return_days']}；20日配对区块Bootstrap
  {result['bootstrap']['samples']}次。
- 滚动窗口：756交易日，步长21日，共{rolling['windows']}窗。
- 原历史研究门槛不因本审计而覆盖。

## 原样本

- 年化收益：候选 {original['candidate_annualized_return']:.2%} /
  标普 {original['sp500_annualized_return']:.2%} /
  提升 {original['return_lift']:.2%}
- Sharpe：候选 {original['candidate_sharpe']:.3f} /
  标普 {original['sp500_sharpe']:.3f} /
  提升 {original['sharpe_lift']:.3f}
- 最大回撤：候选 {original['candidate_max_drawdown']:.2%} /
  标普 {original['sp500_max_drawdown']:.2%} /
  改善 {original['drawdown_improvement']:.2%}

## Bootstrap

- P(年化收益提升≥0.5%)：
  {probabilities['return_lift_at_least_05pct']:.1%}
- P(Sharpe提升≥0.05)：
  {probabilities['sharpe_lift_at_least_005']:.1%}
- P(回撤改善>0)：
  {probabilities['drawdown_improvement_positive']:.1%}
- 收益提升 P05/中位/P95：
  {distributions['return_lift']['p05']:.2%} /
  {distributions['return_lift']['median']:.2%} /
  {distributions['return_lift']['p95']:.2%}

## 滚动三年

- 收益提升为正占比：{rolling['positive_return_lift_share']:.1%}
- Sharpe提升为正占比：{rolling['positive_sharpe_lift_share']:.1%}
- 回撤改善为正占比：{rolling['positive_drawdown_improvement_share']:.1%}
- 收益提升 P10/中位/P90：
  {rolling['return_lift_p10']:.2%} /
  {rolling['return_lift_median']:.2%} /
  {rolling['return_lift_p90']:.2%}

## 冻结门槛

{checks}

结论：`{result['classification']}`。源策略结论保持不变，但统计证据按本审计单独解释。
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
