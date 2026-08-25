"""513650与513500作为境内标普500载体的历史等价性审计。"""

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

from examples import nasdaq100_domestic_etf_execution_feasibility_study as support
from examples import sp500_domestic_etf_execution_feasibility_study as feasibility
from examples import nasdaq_gold_sp500_hurdle_study as base
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


EXPERIMENT_ID = "sp500_etf_513650_513500_instrument_equivalence_audit_v1"
REPORT_PATH = Path(
    "docs/research/sp500-etf-513650-513500-instrument-equivalence-audit-v1.md"
)
CANDIDATE = "513650.SH"
CONTROL = base.SP500
START_DATE = "20230404"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="513650与513500标普500载体等价性 V1",
    category="execution_audit",
    hypothesis=(
        "当前溢价更低且容量合格的513650，自上市以来是否与原机会成本载体"
        "513500具有足够高的日收益相关、接近1的Beta和可接受的跟踪差"
    ),
    definition={
        "source_feasibility": feasibility.EXPERIMENT_ID,
        "candidate": CANDIDATE,
        "control": CONTROL,
        "start_date": START_DATE,
        "return_source": "Tushare fund_daily pct_chg",
        "strategy_returns_used": False,
        "frozen_gate": {
            "common_days_min": 700,
            "daily_return_correlation_min": 0.98,
            "beta_range": [0.95, 1.05],
            "annualized_active_return_abs_max": 0.02,
            "annualized_tracking_error_max": 0.06,
            "worst_absolute_daily_active_return_max": 0.05,
        },
        "does_not_authorize_control_replacement": True,
        "does_not_authorize_strategy_substitution": True,
        "promotion_scope": "instrument_equivalence_only",
        "methodology_version": "daily_pct_chg_overlap_v1",
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
        require_feasibility_passed(paths)
        resolved = client or support.TushareFundClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        )
        result, returns = calculate(resolved, normalized, paths)
        complete_attempt(attempt, result, returns)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    client: Any,
    as_of_date: str,
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame]:
    frames = {
        symbol: normalize_returns(
            client.daily(symbol, START_DATE, as_of_date),
            symbol,
        )
        for symbol in [CANDIDATE, CONTROL]
    }
    returns = frames[CANDIDATE].merge(
        frames[CONTROL],
        on="trade_date",
        how="inner",
        suffixes=("_candidate", "_control"),
        validate="one_to_one",
    ).sort_values("trade_date")
    if returns.empty:
        raise ValueError("513650与513500没有共同日收益")
    candidate = returns["return_candidate"]
    control = returns["return_control"]
    active = candidate - control
    control_variance = float(control.var(ddof=1))
    beta = (
        float(candidate.cov(control) / control_variance)
        if control_variance > 0
        else float("nan")
    )
    annualized_active = float(active.mean() * 252)
    tracking_error = float(active.std(ddof=1) * math.sqrt(252))
    correlation = float(candidate.corr(control))
    cumulative_candidate = float((1.0 + candidate).prod() - 1.0)
    cumulative_control = float((1.0 + control).prod() - 1.0)
    checks = {
        "at_least_700_common_days": len(returns) >= 700,
        "daily_return_correlation_at_least_098": correlation >= 0.98,
        "beta_between_095_and_105": 0.95 <= beta <= 1.05,
        "annualized_active_return_within_2pct": (
            abs(annualized_active) <= 0.02
        ),
        "annualized_tracking_error_within_6pct": tracking_error <= 0.06,
        "worst_absolute_daily_active_return_within_5pct": (
            float(active.abs().max()) <= 0.05
        ),
    }
    passed = all(checks.values())
    result = {
        "as_of_date": as_of_date,
        "start_date": START_DATE,
        "common_days": int(len(returns)),
        "daily_return_correlation": correlation,
        "beta_vs_513500": beta,
        "annualized_active_return": annualized_active,
        "annualized_tracking_error": tracking_error,
        "worst_absolute_daily_active_return": float(active.abs().max()),
        "cumulative_candidate_return": cumulative_candidate,
        "cumulative_control_return": cumulative_control,
        "cumulative_return_difference": (
            cumulative_candidate - cumulative_control
        ),
        "checks": checks,
        "classification": (
            "INSTRUMENT_RETURN_EQUIVALENCE_PASSED"
            if passed
            else "INSTRUMENT_RETURN_EQUIVALENCE_FAILED"
        ),
        "control_replacement_authorized": False,
        "strategy_substitution_authorized": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, returns


def normalize_returns(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {"trade_date", "pct_chg"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{symbol} fund_daily缺少字段: {missing}")
    data = frame[["trade_date", "pct_chg"]].copy()
    data["trade_date"] = (
        data["trade_date"].astype(str).str.replace("-", "")
    )
    data["return"] = (
        pd.to_numeric(data["pct_chg"], errors="coerce") / 100.0
    )
    data = data[
        data["trade_date"].ge(START_DATE)
        & data["return"].notna()
        & np.isfinite(data["return"])
    ]
    return data.sort_values("trade_date").drop_duplicates("trade_date")


def require_feasibility_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        feasibility.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("标普500载体可行性依赖尚未成功")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError(
            f"标普500载体可行性未通过: {latest.get('outcome')}"
        )
    eligible = set((latest.get("metrics") or {}).get("eligible_symbols") or [])
    if CANDIDATE not in eligible:
        raise RuntimeError(f"{CANDIDATE}不在可行载体列表")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    returns: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    returns_path = attempt.output_dir / "daily_return_comparison.csv"
    returns.to_csv(returns_path, index=False)
    metrics_path = attempt.output_dir / "equivalence_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "513650与513500日收益等价性通过，但替换仍需人工批准"
            if result["classification"].endswith("PASSED")
            else "513650与513500的历史日收益等价性未通过"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "载体等价性报告"),
            ExperimentArtifact("returns", returns_path, "日收益比较"),
            ExperimentArtifact("metrics", metrics_path, "等价性指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 513650与513500标普500载体等价性 V1

- 区间：{result['start_date']} 至 {result['as_of_date']}；
  共同交易日：{result['common_days']}。
- 日收益相关：{result['daily_return_correlation']:.4f}；
  Beta：{result['beta_vs_513500']:.4f}。
- 年化主动收益：{result['annualized_active_return']:.2%}；
  年化跟踪误差：{result['annualized_tracking_error']:.2%}。
- 最差绝对单日主动收益：
  {result['worst_absolute_daily_active_return']:.2%}。
- 累计收益513650/513500：
  {result['cumulative_candidate_return']:.2%} /
  {result['cumulative_control_return']:.2%}。
- 分类：`{result['classification']}`。

## 等价性门槛

{checks}

本审计只验证历史日收益等价性；不授权替换机会成本对照或策略标的，
也不代表未来溢价和跟踪误差稳定。
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
