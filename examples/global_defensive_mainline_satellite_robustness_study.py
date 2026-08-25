"""全球防守核心×主线卫星80/20通过候选的权重与抽样稳健性审计。"""

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

from examples import global_defensive_mainline_satellite_study as base
from examples.quality_mainline_diversification_metrics import build_period_metrics
from examples.quality_mainline_diversification_study import (
    AllocationRun,
    simulate_monthly_allocation,
)
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


EXPERIMENT_ID = "global_defensive_mainline_satellite_robustness_v1"
REPORT_PATH = Path(
    "docs/research/global-defensive-mainline-satellite-robustness-v1.md"
)
SCENARIOS = {
    "satellite_10pct_10bps": (0.10, 10.0),
    "baseline_20pct_10bps": (0.20, 10.0),
    "satellite_30pct_10bps": (0.30, 10.0),
    "baseline_20pct_100bps": (0.20, 100.0),
}
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_BLOCK_DAYS = 20
BOOTSTRAP_SEED = 20260729

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球防守×主线80/20稳健性 V1",
    category="portfolio_robustness",
    hypothesis=(
        "已通过的80/20组合是否在10%与30%卫星邻域、100bps调拨压力、滚动一年和"
        "20日区块重抽样下仍保留正收益、受控回撤及相对核心的收益提升"
    ),
    definition={
        "dependency": base.EXPERIMENT_ID,
        "source": "same_monitoring_net_cost_histories",
        "scenarios": SCENARIOS,
        "selection_from_scenarios": False,
        "rolling_window_days": 252,
        "bootstrap": {
            "samples": BOOTSTRAP_SAMPLES,
            "block_days": BOOTSTRAP_BLOCK_DAYS,
            "seed": BOOTSTRAP_SEED,
            "statistic": "annualized_return_lift_vs_core",
        },
        "gate": {
            "all_neighborhood_returns_min": 0.10,
            "all_neighborhood_drawdown_floor": -0.20,
            "all_neighborhood_sharpes_min": 0.95,
            "all_neighborhood_folds_positive": True,
            "stress_100bps_return_min": 0.095,
            "stress_100bps_drawdown_floor": -0.19,
            "stress_100bps_sharpe_min": 0.90,
            "rolling_252d_positive_share_min": 0.70,
            "bootstrap_return_lift_positive_probability_min": 0.75,
            "bootstrap_return_lift_p05_floor": -0.03,
        },
        "parameters_fixed_before_loading_daily_returns": True,
        "promotion_scope": "robustness_only_no_production_registration",
        "methodology_version": "weight_cost_block_bootstrap_v1",
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
        require_baseline_passed(paths)
        result, scenario_daily, bootstrap = calculate(paths, as_of_date)
        complete_attempt(attempt, result, scenario_daily, bootstrap)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame], pd.DataFrame]:
    histories = base.load_strategy_histories(paths, as_of_date)
    audit = base.audit_common_history(histories)
    if not audit["passed"]:
        raise ValueError(f"strategy history audit failed: {audit}")
    common = histories[base.CORE_ID].merge(
        histories[base.SATELLITE_ID][["trade_date", "nav"]],
        on="trade_date",
        how="inner",
        suffixes=("_core", "_satellite"),
        validate="one_to_one",
    )
    runs = {
        name: simulate_monthly_allocation(
            common,
            core_weight=1.0 - satellite_weight,
            satellite_weight=satellite_weight,
            cost_bps=cost_bps,
        )
        for name, (satellite_weight, cost_bps) in SCENARIOS.items()
    }
    periods = {
        name: (start, audit["end_date"] if end == "LATEST" else end)
        for name, (start, end) in base.FOLDS.items()
    }
    periods["full"] = (audit["start_date"], audit["end_date"])
    metrics = {
        name: build_period_metrics(run.daily, periods)
        for name, run in runs.items()
    }
    baseline = runs["baseline_20pct_10bps"].daily
    rolling = rolling_return_diagnostics(baseline)
    bootstrap = block_bootstrap_return_lift(
        baseline,
        samples=BOOTSTRAP_SAMPLES,
        block_days=BOOTSTRAP_BLOCK_DAYS,
        seed=BOOTSTRAP_SEED,
    )
    bootstrap_summary = {
        "samples": len(bootstrap),
        "p05": float(bootstrap["annualized_return_lift"].quantile(0.05)),
        "median": float(bootstrap["annualized_return_lift"].median()),
        "p95": float(bootstrap["annualized_return_lift"].quantile(0.95)),
        "positive_probability": float(
            bootstrap["annualized_return_lift"].gt(0).mean()
        ),
    }
    gate = evaluate_gate(metrics, rolling, bootstrap_summary)
    result = {
        "experiment_id": EXPERIMENT_ID,
        "as_of_date": as_of_date,
        "history_audit": audit,
        "scenario_metrics": {
            name: values["full"]["combined"]
            for name, values in metrics.items()
        },
        "scenario_fold_metrics": {
            name: {
                fold: values[fold]["combined"]
                for fold in base.FOLDS
            }
            for name, values in metrics.items()
        },
        "rolling_diagnostics": rolling,
        "bootstrap": bootstrap_summary,
        "gate": gate,
        "decision": (
            "ROBUSTNESS_PASSED_CONTINUE_FORWARD_OBSERVATION"
            if gate["passed"]
            else "ROBUSTNESS_FAILED_NO_PROMOTION"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, {name: run.daily for name, run in runs.items()}, bootstrap


def rolling_return_diagnostics(daily: pd.DataFrame) -> dict[str, float | int]:
    frame = daily.copy()
    portfolio = frame["portfolio_nav"].astype(float)
    core = frame["core_nav"].astype(float)
    rolling_return = portfolio / portfolio.shift(252) - 1.0
    rolling_core = core / core.shift(252) - 1.0
    valid = pd.DataFrame(
        {
            "return": rolling_return,
            "core_return": rolling_core,
        }
    ).dropna()
    return {
        "windows": len(valid),
        "positive_share": float(valid["return"].gt(0).mean()),
        "beat_core_share": float(
            valid["return"].gt(valid["core_return"]).mean()
        ),
        "worst_252d_return": float(valid["return"].min()),
        "median_252d_return": float(valid["return"].median()),
    }


def block_bootstrap_return_lift(
    daily: pd.DataFrame,
    *,
    samples: int,
    block_days: int,
    seed: int,
) -> pd.DataFrame:
    candidate = daily["portfolio_nav"].astype(float).pct_change().dropna()
    core = daily["core_nav"].astype(float).pct_change().dropna()
    aligned = pd.concat(
        [candidate.rename("candidate"), core.rename("core")],
        axis=1,
    ).dropna()
    values = aligned.to_numpy(dtype=float)
    n = len(values)
    if n < block_days * 2:
        raise ValueError("insufficient history for block bootstrap")
    rng = np.random.default_rng(seed)
    rows = []
    blocks_needed = int(np.ceil(n / block_days))
    max_start = n - block_days
    for _ in range(samples):
        starts = rng.integers(0, max_start + 1, size=blocks_needed)
        indexes = np.concatenate(
            [np.arange(start, start + block_days) for start in starts]
        )[:n]
        sample = values[indexes]
        candidate_annual = float(
            np.prod(1.0 + sample[:, 0]) ** (252.0 / n) - 1.0
        )
        core_annual = float(
            np.prod(1.0 + sample[:, 1]) ** (252.0 / n) - 1.0
        )
        rows.append(
            {
                "candidate_annualized_return": candidate_annual,
                "core_annualized_return": core_annual,
                "annualized_return_lift": candidate_annual - core_annual,
            }
        )
    return pd.DataFrame(rows)


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, dict[str, float]]]],
    rolling: dict[str, float | int],
    bootstrap: dict[str, float | int],
) -> dict[str, Any]:
    neighborhoods = [
        metrics[name]
        for name in [
            "satellite_10pct_10bps",
            "baseline_20pct_10bps",
            "satellite_30pct_10bps",
        ]
    ]
    fulls = [item["full"]["combined"] for item in neighborhoods]
    fold_values = [
        item[fold]["combined"]
        for item in neighborhoods
        for fold in base.FOLDS
    ]
    stress = metrics["baseline_20pct_100bps"]["full"]["combined"]
    checks = {
        "all_neighborhood_returns_at_least_10pct": min(
            item["annualized_return"] for item in fulls
        )
        >= 0.10,
        "all_neighborhood_drawdowns_within_20pct": min(
            item["max_drawdown"] for item in fulls
        )
        >= -0.20,
        "all_neighborhood_sharpes_at_least_095": min(
            item["sharpe"] for item in fulls
        )
        >= 0.95,
        "all_neighborhood_folds_positive": all(
            item["annualized_return"] > 0 for item in fold_values
        ),
        "stress_100bps_return_at_least_95pct": (
            stress["annualized_return"] >= 0.095
        ),
        "stress_100bps_drawdown_within_19pct": (
            stress["max_drawdown"] >= -0.19
        ),
        "stress_100bps_sharpe_at_least_090": stress["sharpe"] >= 0.90,
        "rolling_252d_positive_share_at_least_70pct": (
            float(rolling["positive_share"]) >= 0.70
        ),
        "bootstrap_lift_positive_probability_at_least_75pct": (
            float(bootstrap["positive_probability"]) >= 0.75
        ),
        "bootstrap_lift_p05_above_minus_3pct": (
            float(bootstrap["p05"]) >= -0.03
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def require_baseline_passed(paths: RuntimePaths) -> None:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        base.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("80/20基线实验尚未成功")
    if latest.get("outcome") != "PASSED_RESEARCH_GATE":
        raise RuntimeError("80/20基线未通过研究门槛")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    scenario_daily: dict[str, pd.DataFrame],
    bootstrap: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    metrics_path = attempt.output_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    daily_path = attempt.output_dir / "scenario_daily_nav.csv"
    pd.concat(
        [
            frame.assign(scenario=name)
            for name, frame in scenario_daily.items()
        ],
        ignore_index=True,
    ).to_csv(daily_path, index=False)
    bootstrap_path = attempt.output_dir / "bootstrap_return_lift.csv"
    bootstrap.to_csv(bootstrap_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_ROBUSTNESS" if passed else "REJECTED",
        decision_reason=(
            "80/20组合通过权重、成本、滚动窗口与区块抽样稳健性门槛"
            if passed
            else "80/20组合未通过至少一项稳健性门槛，不晋级"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "80/20稳健性报告"),
            ExperimentArtifact("metrics", metrics_path, "稳健性指标"),
            ExperimentArtifact("scenario_daily", daily_path, "场景净值"),
            ExperimentArtifact("bootstrap", bootstrap_path, "区块抽样分布"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    scenarios = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for name, item in result["scenario_metrics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    rolling = result["rolling_diagnostics"]
    bootstrap = result["bootstrap"]
    return f"""# 全球防守核心 × 主线卫星 80/20 稳健性 V1

| 场景 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{scenarios}

## 滚动与重抽样

- 252日滚动窗口：{rolling['windows']}；正收益占比：
  {rolling['positive_share']:.2%}；跑赢核心占比：
  {rolling['beat_core_share']:.2%}；最差252日：
  {rolling['worst_252d_return']:.2%}。
- 20日区块 bootstrap：{bootstrap['samples']}次；相对核心年化收益提升
  P05/中位/P95 = {bootstrap['p05']:.2%} /
  {bootstrap['median']:.2%} / {bootstrap['p95']:.2%}；
  提升为正概率 {bootstrap['positive_probability']:.2%}。

## 冻结门槛

{checks}

结论：`{result['decision']}`。不修改底层策略、观察名单或生产调度。
"""


def _data_version(paths: RuntimePaths) -> str:
    stat = paths.monitoring_path.stat()
    return f"monitoring:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260728")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
