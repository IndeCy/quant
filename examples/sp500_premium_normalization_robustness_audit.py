"""用月度聚类和非重叠事件审计标普500高溢价归一化结论。"""

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

from examples import nasdaq100_domestic_etf_execution_feasibility_study as support
from examples import nasdaq_gold_sp500_hurdle_study as base
from examples import sp500_etf_premium_normalization_risk_audit as source
from runtime.config import get_config_value
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


EXPERIMENT_ID = "sp500_premium_normalization_robustness_audit_v1"
REPORT_PATH = Path(
    "docs/research/sp500-premium-normalization-robustness-audit-v1.md"
)
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20260729
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="标普500高溢价归一化稳健性 V1",
    category="execution_audit",
    hypothesis=(
        "513500高溢价后的20日负效应，在控制重叠窗口后是否仍由月度聚类、"
        "非重叠事件与聚类Bootstrap共同支持"
    ),
    definition={
        "source_normalization_audit": source.EXPERIMENT_ID,
        "control": source.source.source.CONTROL,
        "premium_threshold": source.PREMIUM_THRESHOLD,
        "forward_trading_days": source.FORWARD_DAYS,
        "overlap_controls": {
            "calendar_month_cluster_medians": True,
            "non_overlapping_event_gap": source.FORWARD_DAYS,
            "bootstrap_unit": "calendar_month_median",
            "bootstrap_draws": BOOTSTRAP_DRAWS,
            "bootstrap_seed": BOOTSTRAP_SEED,
        },
        "frozen_gate": {
            "valid_observations_min": 700,
            "high_premium_months_min": 10,
            "negative_month_median_share_min": 0.60,
            "bootstrap_probability_cluster_median_negative_min": 0.80,
            "non_overlapping_events_min": 10,
            "non_overlapping_median_effect_max": 0.0,
        },
        "does_not_use_strategy_returns": True,
        "does_not_define_a_trading_signal": True,
        "does_not_authorize_instrument_substitution": True,
        "promotion_scope": "overlap_robustness_only",
        "methodology_version": "monthly_cluster_nonoverlap_bootstrap_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    normalized = min(str(as_of_date).replace("-", ""), base.RELIABLE_AS_OF)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized,
        data_version=data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_source_completed(paths)
        resolved = client or support.TushareFundClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        )
        result, high, monthly, non_overlapping = calculate(
            resolved,
            normalized,
            paths,
        )
        complete_attempt(attempt, result, high, monthly, non_overlapping)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    client: Any,
    as_of_date: str,
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    symbol = source.source.source.CONTROL
    matched = source.source.normalize_matched(
        client.nav(symbol, source.source.source.START_DATE, as_of_date),
        client.daily(symbol, source.source.source.START_DATE, as_of_date),
        symbol,
    )
    observations = source.build_forward_observations(matched)
    high = observations[observations["high_premium"]].copy()
    high["year_month"] = high["trade_date"].astype(str).str[:6]
    monthly = (
        high.groupby("year_month", as_index=False)
        .agg(
            observation_count=("forward_premium_effect", "size"),
            median_forward_effect=("forward_premium_effect", "median"),
        )
        .sort_values("year_month")
    )
    non_overlapping = select_non_overlapping(high, source.FORWARD_DAYS)
    cluster_values = monthly["median_forward_effect"].to_numpy(dtype=float)
    probability_negative = bootstrap_negative_median_probability(
        cluster_values,
        BOOTSTRAP_DRAWS,
        BOOTSTRAP_SEED,
    )
    checks = {
        "at_least_700_valid_observations": len(observations) >= 700,
        "at_least_10_high_premium_months": len(monthly) >= 10,
        "negative_month_median_share_at_least_60pct": (
            float(monthly["median_forward_effect"].lt(0).mean()) >= 0.60
        ),
        "bootstrap_cluster_median_negative_probability_at_least_80pct": (
            probability_negative >= 0.80
        ),
        "at_least_10_non_overlapping_events": len(non_overlapping) >= 10,
        "non_overlapping_median_effect_non_positive": (
            float(non_overlapping["forward_premium_effect"].median()) <= 0.0
        ),
    }
    result = {
        "as_of_date": as_of_date,
        "control_symbol": symbol,
        "valid_forward_observations": int(len(observations)),
        "overlapping_high_premium_observations": int(len(high)),
        "high_premium_month_count": int(len(monthly)),
        "negative_month_median_share": float(
            monthly["median_forward_effect"].lt(0).mean()
        ),
        "median_of_monthly_medians": float(
            monthly["median_forward_effect"].median()
        ),
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_probability_cluster_median_negative": probability_negative,
        "non_overlapping_event_count": int(len(non_overlapping)),
        "non_overlapping_median_forward_effect": float(
            non_overlapping["forward_premium_effect"].median()
        ),
        "non_overlapping_negative_effect_probability": float(
            non_overlapping["forward_premium_effect"].lt(0).mean()
        ),
        "checks": checks,
        "classification": (
            "NORMALIZATION_RISK_ROBUST_TO_OVERLAP_CONTROL"
            if all(checks.values())
            else "NORMALIZATION_RISK_SENSITIVE_TO_OVERLAP_CONTROL"
        ),
        "strategy_returns_used": False,
        "trading_signal_defined": False,
        "instrument_substitution_authorized": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, high, monthly, non_overlapping


def select_non_overlapping(
    high: pd.DataFrame,
    minimum_gap: int,
) -> pd.DataFrame:
    selected_indices: list[int] = []
    last_position = -minimum_gap
    for position, (_, row) in enumerate(
        high.sort_values("trade_date").iterrows()
    ):
        original_position = int(row.name)
        if original_position - last_position >= minimum_gap:
            selected_indices.append(original_position)
            last_position = original_position
    return high.loc[selected_indices].sort_values("trade_date").reset_index(
        drop=True
    )


def bootstrap_negative_median_probability(
    values: np.ndarray,
    draws: int,
    seed: int,
) -> float:
    if len(values) == 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(draws, len(values)))
    medians = np.median(values[indices], axis=1)
    return float(np.mean(medians < 0.0))


def require_source_completed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    expected = "CONTROL_PREMIUM_NORMALIZATION_RISK_CANDIDATE_CURRENTLY_LOWER"
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("标普500高溢价归一化风险依赖尚未成功")
    if latest.get("outcome") != expected:
        raise RuntimeError(
            f"标普500高溢价归一化结论不符: {latest.get('outcome')}"
        )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    high: pd.DataFrame,
    monthly: pd.DataFrame,
    non_overlapping: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    high_path = attempt.output_dir / "high_premium_observations.csv"
    high.to_csv(high_path, index=False)
    monthly_path = attempt.output_dir / "monthly_clusters.csv"
    monthly.to_csv(monthly_path, index=False)
    non_overlap_path = attempt.output_dir / "non_overlapping_events.csv"
    non_overlapping.to_csv(non_overlap_path, index=False)
    metrics_path = attempt.output_dir / "robustness_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "月度聚类Bootstrap与非重叠事件仍支持高溢价归一化风险"
            if result["classification"].endswith("OVERLAP_CONTROL")
            and "ROBUST" in result["classification"]
            else "控制重叠窗口后，高溢价归一化风险证据不足"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "重叠稳健性报告"),
            ExperimentArtifact("monthly", monthly_path, "月度聚类统计"),
            ExperimentArtifact(
                "non_overlapping",
                non_overlap_path,
                "非重叠高溢价事件",
            ),
            ExperimentArtifact("metrics", metrics_path, "稳健性指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 标普500高溢价归一化稳健性 V1

- 控制标的：`{result['control_symbol']}`。
- 原重叠高溢价样本：
  {result['overlapping_high_premium_observations']}；高溢价月份：
  {result['high_premium_month_count']}。
- 月度中位为负占比：{result['negative_month_median_share']:.1%}；
  月度中位数的中位：{result['median_of_monthly_medians']:.2%}。
- 月度聚类Bootstrap中位为负概率：
  {result['bootstrap_probability_cluster_median_negative']:.1%}。
- 非重叠事件：{result['non_overlapping_event_count']}；中位效应：
  {result['non_overlapping_median_forward_effect']:.2%}；负效应概率：
  {result['non_overlapping_negative_effect_probability']:.1%}。
- 分类：`{result['classification']}`。

## 冻结门槛

{checks}

本审计控制20日远期窗口重叠造成的伪精度，不构成择时信号或标的替换授权。
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
