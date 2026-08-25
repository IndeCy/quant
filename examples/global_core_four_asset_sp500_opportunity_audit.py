"""四资产组合相对直接标普收益机会成本的配对区块抽样审计。"""

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

from examples import global_core_nasdaq_gold_four_asset_study as base
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


EXPERIMENT_ID = "global_core_four_asset_sp500_opportunity_audit_v1"
REPORT_PATH = Path(
    "docs/research/global-core-four-asset-sp500-opportunity-audit-v1.md"
)
HURDLE = 0.005
SAMPLES = 10000
BLOCK_DAYS = 20
SEED = 20260729

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="四资产组合相对标普机会成本审计 V1",
    category="relative_return_robustness",
    hypothesis=(
        "四资产组合相对直接标普约-0.16%的年化收益差，是否在滚动252日和20日区块"
        "bootstrap下稳定无法达到预注册的+0.50%机会成本门槛"
    ),
    definition={
        "dependency": base.EXPERIMENT_ID,
        "hurdle": HURDLE,
        "statistics": [
            "full_annualized_return_lift",
            "rolling_252d_return_lift",
            "paired_20d_block_bootstrap_annualized_lift",
        ],
        "bootstrap": {
            "samples": SAMPLES,
            "block_days": BLOCK_DAYS,
            "seed": SEED,
        },
        "classification": {
            "robust_failure_if_probability_meeting_hurdle_max": 0.20,
            "robust_pass_if_probability_meeting_hurdle_min": 0.80,
            "otherwise": "INCONCLUSIVE",
        },
        "override_original_gate": False,
        "promotion_scope": "audit_only_no_registration",
        "methodology_version": "paired_opportunity_cost_blocks_v1",
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
        require_single_gate_failure(paths)
        result, aligned, bootstrap = calculate(paths)
        complete_attempt(attempt, result, aligned, bootstrap)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    frame = load_candidate_artifact(paths)
    aligned = build_return_frame(frame)
    years = len(aligned) / 252.0
    candidate_annual = (
        float((1.0 + aligned["candidate"]).prod()) ** (1.0 / years) - 1.0
    )
    sp500_annual = (
        float((1.0 + aligned["sp500"]).prod()) ** (1.0 / years) - 1.0
    )
    rolling_candidate = (
        (1.0 + aligned["candidate"]).rolling(252).apply(np.prod, raw=True) - 1.0
    )
    rolling_sp500 = (
        (1.0 + aligned["sp500"]).rolling(252).apply(np.prod, raw=True) - 1.0
    )
    rolling_lift = (rolling_candidate - rolling_sp500).dropna()
    bootstrap = block_bootstrap_lifts(
        aligned[["candidate", "sp500"]],
        samples=SAMPLES,
        block_days=BLOCK_DAYS,
        seed=SEED,
    )
    probability_hurdle = float(
        bootstrap["annualized_return_lift"].ge(HURDLE).mean()
    )
    probability_positive = float(
        bootstrap["annualized_return_lift"].gt(0).mean()
    )
    if probability_hurdle <= 0.20:
        classification = "ROBUST_OPPORTUNITY_COST_FAILURE"
    elif probability_hurdle >= 0.80:
        classification = "ROBUST_OPPORTUNITY_COST_PASS"
    else:
        classification = "INCONCLUSIVE"
    result = {
        "experiment_id": EXPERIMENT_ID,
        "common_returns": len(aligned),
        "full": {
            "candidate_annualized_return": candidate_annual,
            "sp500_annualized_return": sp500_annual,
            "annualized_return_lift": candidate_annual - sp500_annual,
        },
        "rolling_252d": {
            "windows": len(rolling_lift),
            "p10": float(rolling_lift.quantile(0.10)),
            "median": float(rolling_lift.median()),
            "p90": float(rolling_lift.quantile(0.90)),
            "positive_share": float(rolling_lift.gt(0).mean()),
            "hurdle_share": float(rolling_lift.ge(HURDLE).mean()),
        },
        "bootstrap": {
            "samples": len(bootstrap),
            "p05": float(
                bootstrap["annualized_return_lift"].quantile(0.05)
            ),
            "median": float(bootstrap["annualized_return_lift"].median()),
            "p95": float(
                bootstrap["annualized_return_lift"].quantile(0.95)
            ),
            "positive_probability": probability_positive,
            "hurdle_probability": probability_hurdle,
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


def build_return_frame(frame: pd.DataFrame) -> pd.DataFrame:
    candidate = frame[base.EXPERIMENT_ID].astype(float).pct_change()
    sp500 = frame[base.SP500_CONTROL_ID].astype(float).pct_change()
    return pd.DataFrame(
        {
            "trade_date": frame["trade_date"].astype(str),
            "candidate": candidate,
            "sp500": sp500,
        }
    ).dropna()


def block_bootstrap_lifts(
    returns: pd.DataFrame,
    *,
    samples: int,
    block_days: int,
    seed: int,
) -> pd.DataFrame:
    values = returns[["candidate", "sp500"]].to_numpy(dtype=float)
    n = len(values)
    if n < block_days * 2:
        raise ValueError("insufficient returns for block bootstrap")
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
        candidate = float(
            np.prod(1.0 + sample[:, 0]) ** (252.0 / n) - 1.0
        )
        sp500 = float(
            np.prod(1.0 + sample[:, 1]) ** (252.0 / n) - 1.0
        )
        rows.append(candidate - sp500)
    return pd.DataFrame({"annualized_return_lift": rows})


def load_candidate_artifact(paths: RuntimePaths) -> pd.DataFrame:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        base.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest:
        raise RuntimeError("四资产组合实验不存在")
    path = Path(str(latest["output_dir"])) / "daily_nav.csv"
    return pd.read_csv(path, dtype={"trade_date": str})


def require_single_gate_failure(paths: RuntimePaths) -> None:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        base.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("outcome") != "REJECTED":
        raise RuntimeError("四资产组合不是可审计的REJECTED结果")
    checks = latest.get("metrics", {}).get("gate", {}).get("checks", {})
    failed = [name for name, value in checks.items() if not value]
    if failed != ["return_lift_vs_sp500_at_least_05pct"]:
        raise RuntimeError(f"四资产组合并非仅机会成本失败: {failed}")


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
    bootstrap_path = attempt.output_dir / "bootstrap_lifts.csv"
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
            f"相对标普机会成本分类为{result['classification']}；原门槛不覆盖"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "标普机会成本审计报告"),
            ExperimentArtifact("aligned_returns", aligned_path, "配对日收益"),
            ExperimentArtifact("bootstrap", bootstrap_path, "区块抽样收益差"),
            ExperimentArtifact("metrics", metrics_path, "审计指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    full = result["full"]
    rolling = result["rolling_252d"]
    bootstrap = result["bootstrap"]
    return f"""# 四资产组合相对直接标普机会成本审计 V1

- 全期候选/标普年化：{full['candidate_annualized_return']:.2%} /
  {full['sp500_annualized_return']:.2%}；差值：
  {full['annualized_return_lift']:.2%}。
- 252日滚动差 P10/中位/P90：{rolling['p10']:.2%} /
  {rolling['median']:.2%} / {rolling['p90']:.2%}；
  正差占比 {rolling['positive_share']:.2%}，达到+0.5%占比
  {rolling['hurdle_share']:.2%}。
- 区块bootstrap差 P05/中位/P95：{bootstrap['p05']:.2%} /
  {bootstrap['median']:.2%} / {bootstrap['p95']:.2%}；
  正差概率 {bootstrap['positive_probability']:.2%}，达到+0.5%概率
  {bootstrap['hurdle_probability']:.2%}。

结论：`{result['classification']}`。不覆盖原冻结门槛，组合保持拒绝。
"""


def _data_version(paths: RuntimePaths) -> str:
    stat = paths.system_state_path.stat()
    return f"system_state:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260615")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
