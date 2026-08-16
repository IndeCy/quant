"""纳指黄金60/40在容量持续恢复后的独立表现审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq_gold_capacity_failure_attribution_audit as capacity
from examples import nasdaq_gold_sp500_hurdle_study as base
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


EXPERIMENT_ID = "nasdaq_gold_60_40_post_capacity_recovery_audit_v1"
REPORT_PATH = Path(
    "docs/research/nasdaq-gold-60-40-post-capacity-recovery-audit-v1.md"
)
BOOTSTRAP_SAMPLES = 10_000
BLOCK_DAYS = 20
SEED = 20260729
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指黄金60/40容量恢复后表现审计 V1",
    category="execution_audit",
    hypothesis=(
        "以成交容量而非收益确定起点后，固定60/40组合是否仍保留相对场内"
        "标普500的收益、Sharpe与回撤优势"
    ),
    definition={
        "source_strategy": base.EXPERIMENT_ID,
        "source_capacity_attribution": capacity.EXPERIMENT_ID,
        "sample_start_rule": (
            "first_trading_day_after_159941_rolling_252d_p90_participation_"
            "stays_below_1pct_for_12_months"
        ),
        "start_selection_uses_returns": False,
        "bootstrap": {
            "paired": True,
            "samples": BOOTSTRAP_SAMPLES,
            "block_days": BLOCK_DAYS,
            "seed": SEED,
        },
        "frozen_gate": {
            "annualized_return_lift_vs_sp500_min": 0.01,
            "sharpe_lift_vs_sp500_min": 0.10,
            "drawdown_worse_vs_sp500_max": 0.02,
            "probability_return_lift_at_least_05pct_min": 0.70,
            "probability_sharpe_lift_at_least_005_min": 0.70,
            "probability_drawdown_improvement_positive_min": 0.70,
            "all_full_calendar_years_positive": True,
        },
        "does_not_override_source_gate": True,
        "does_not_rehabilitate_pre_recovery_backtest": True,
        "promotion_scope": "post_capacity_diagnostic_only",
        "methodology_version": "capacity_anchored_paired_bootstrap_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    normalized = min(str(as_of_date).replace("-", ""), base.RELIABLE_AS_OF)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized,
        data_version=base._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        recovery_date = require_dependencies(paths)
        returns, source_path = statistics.load_returns(paths)
        result, samples, annual = calculate(
            returns,
            source_path,
            recovery_date,
        )
        complete_attempt(attempt, result, samples, annual)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    returns: pd.DataFrame,
    source_path: str,
    recovery_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    recovery_timestamp = pd.Timestamp(recovery_date)
    sample = returns[returns.index > recovery_timestamp].copy()
    if len(sample) < 756:
        raise ValueError("容量恢复后共同收益不足756日")
    original = statistics.compare_metrics(
        sample["candidate"].to_numpy(),
        sample["sp500"].to_numpy(),
    )
    samples = statistics.paired_block_bootstrap(
        sample,
        samples=BOOTSTRAP_SAMPLES,
        block_days=BLOCK_DAYS,
        seed=SEED,
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
    annual = annual_returns(sample)
    full_years = annual[annual["trading_days"].ge(230)]
    checks = evaluate_checks(original, probabilities, full_years)
    if all(checks.values()):
        classification = "POST_CAPACITY_EVIDENCE_PASSED"
    elif sum(probability < 0.50 for probability in probabilities.values()) >= 2:
        classification = "POST_CAPACITY_EVIDENCE_FAILED"
    else:
        classification = "INCONCLUSIVE"
    result = {
        "source_nav_path": source_path,
        "capacity_recovery_date": recovery_date,
        "sample_start": sample.index.min().strftime("%Y%m%d"),
        "sample_end": sample.index.max().strftime("%Y%m%d"),
        "common_return_days": int(len(sample)),
        "original": original,
        "bootstrap": {
            "samples": BOOTSTRAP_SAMPLES,
            "block_days": BLOCK_DAYS,
            "probabilities": probabilities,
            "distributions": distributions,
        },
        "full_calendar_years": full_years.to_dict("records"),
        "checks": checks,
        "classification": classification,
        "source_gate_overridden": False,
        "pre_recovery_backtest_rehabilitated": False,
        "report_path": "",
        "reused": False,
    }
    return result, samples, annual


def annual_returns(returns: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for year, values in returns.groupby(returns.index.year):
        rows.append(
            {
                "year": int(year),
                "trading_days": int(len(values)),
                "candidate_return": float(
                    (1.0 + values["candidate"]).prod() - 1.0
                ),
                "sp500_return": float(
                    (1.0 + values["sp500"]).prod() - 1.0
                ),
            }
        )
    return pd.DataFrame(rows)


def evaluate_checks(
    original: dict[str, float],
    probabilities: dict[str, float],
    full_years: pd.DataFrame,
) -> dict[str, bool]:
    return {
        "annualized_return_lift_vs_sp500_at_least_1pct": (
            original["return_lift"] >= 0.01
        ),
        "sharpe_lift_vs_sp500_at_least_010": (
            original["sharpe_lift"] >= 0.10
        ),
        "drawdown_worse_vs_sp500_within_2pct": (
            original["drawdown_improvement"] >= -0.02
        ),
        "return_lift_probability_at_least_70pct": (
            probabilities["return_lift_at_least_05pct"] >= 0.70
        ),
        "sharpe_lift_probability_at_least_70pct": (
            probabilities["sharpe_lift_at_least_005"] >= 0.70
        ),
        "drawdown_improvement_probability_at_least_70pct": (
            probabilities["drawdown_improvement_positive"] >= 0.70
        ),
        "all_full_calendar_years_positive": bool(
            len(full_years) >= 2
            and full_years["candidate_return"].gt(0).all()
        ),
    }


def require_dependencies(paths: RuntimePaths) -> str:
    repository = SystemRepository(paths.system_state_path)
    expected = {
        base.EXPERIMENT_ID: "PASSED_RESEARCH_GATE",
        capacity.EXPERIMENT_ID: (
            "CURRENT_CAPACITY_RECOVERED_BUT_HISTORICAL_BIAS"
        ),
    }
    recovery_date: str | None = None
    for experiment_id, expected_outcome in expected.items():
        detail = repository.load_experiment_detail(experiment_id)
        latest = detail.get("latest_run") if detail else None
        if not latest or latest.get("status") != "SUCCESS":
            raise RuntimeError(f"依赖未成功: {experiment_id}")
        if latest.get("outcome") != expected_outcome:
            raise RuntimeError(
                f"依赖结论不符: {experiment_id}={latest.get('outcome')}"
            )
        if experiment_id == capacity.EXPERIMENT_ID:
            recovery_date = str(
                latest["metrics"]["nasdaq_persistent_recovery_date"]
            )
    if not recovery_date or recovery_date == "None":
        raise RuntimeError("容量归因没有持续恢复日期")
    return recovery_date


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    samples: pd.DataFrame,
    annual: pd.DataFrame,
) -> None:
    result["report_path"] = str(attempt.paths.root / REPORT_PATH)
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    samples_path = attempt.output_dir / "bootstrap_samples.csv"
    samples.to_csv(samples_path, index=False)
    annual_path = attempt.output_dir / "annual_returns.csv"
    annual.to_csv(annual_path, index=False)
    metrics_path = attempt.output_dir / "post_capacity_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "容量恢复后固定样本仍满足收益、风险和重采样证据门槛"
            if result["classification"] == "POST_CAPACITY_EVIDENCE_PASSED"
            else "容量恢复后样本未满足全部冻结证据门槛"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "容量恢复后表现报告"),
            ExperimentArtifact("bootstrap", samples_path, "配对区块样本"),
            ExperimentArtifact("annual", annual_path, "逐年收益"),
            ExperimentArtifact("metrics", metrics_path, "恢复后审计指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    original = result["original"]
    probabilities = result["bootstrap"]["probabilities"]
    years = "\n".join(
        f"| {item['year']} | {item['trading_days']} | "
        f"{item['candidate_return']:.2%} | {item['sp500_return']:.2%} |"
        for item in result["full_calendar_years"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 纳指黄金60/40容量恢复后表现审计 V1

- 容量恢复起点：{result['capacity_recovery_date']}；收益样本从下一交易日
  {result['sample_start']} 开始，到 {result['sample_end']}。
- 共同收益日：{result['common_return_days']}。
- 分类：{result['classification']}。

## 相对场内标普500

- 候选年化：{original['candidate_annualized_return']:.2%}；
  标普年化：{original['sp500_annualized_return']:.2%}；
  差值：{original['return_lift']:.2%}。
- Sharpe 差：{original['sharpe_lift']:.3f}；最大回撤改善：
  {original['drawdown_improvement']:.2%}。
- Bootstrap达到收益差0.5%的概率：
  {probabilities['return_lift_at_least_05pct']:.2%}。
- Bootstrap达到Sharpe差0.05的概率：
  {probabilities['sharpe_lift_at_least_005']:.2%}。
- Bootstrap回撤改善为正的概率：
  {probabilities['drawdown_improvement_positive']:.2%}。

| 完整年度 | 交易日 | 候选 | 场内标普 |
|---:|---:|---:|---:|
{years}

## 冻结门槛

{checks}

样本起点完全由成交容量恢复确定，不读取收益择时。本审计不覆盖源容量风险，
也不把2019至2022的历史回测追认为可成交。
"""


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
