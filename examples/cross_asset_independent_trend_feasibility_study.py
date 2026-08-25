"""五资产独立趋势槽位的回测前数据门禁。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples.cross_asset_independent_trend_feasibility_report import render_report
from examples.cross_asset_dual_momentum_study import (
    ASSET_NAMES,
    DEFENSIVE_ASSET,
    LOAD_START,
    RISKY_ASSETS,
    STUDY_START,
)
from factors.etf_independent_trend import calculate_independent_trend_states
from factors.etf_momentum import month_end_signal_dates
from portfolio.independent_trend_slots import build_independent_trend_slot_targets
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "cross_asset_independent_trend_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/cross-asset-independent-trend-data-feasibility-v1.md"
)
FAST_WINDOW = 60
SLOW_WINDOW = 120
MIN_CONSTRUCTIBLE_SHARE = 0.98
MIN_COMMON_CALENDAR_RETENTION = 0.95
MAX_STALENESS_CALENDAR_DAYS = 10
MIN_ACTIVE_SHARE = 0.10
MAX_ACTIVE_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="五资产独立趋势槽位数据可行性 V1",
    category="data_feasibility",
    hypothesis="五资产统一qfq历史能否稳定支持独立MA60/MA120趋势槽位",
    definition={
        "asset_pool": {
            "risky": RISKY_ASSETS,
            "defensive": DEFENSIVE_ASSET,
            "roles_fixed_before_backtest": True,
        },
        "signal": {
            "formula": "ma60_gt_ma120",
            "independent_per_asset": True,
            "signal_time": "month_end_close",
        },
        "portfolio_preview": {
            "risk_slot_weight": 0.25,
            "inactive_slot_to": DEFENSIVE_ASSET,
            "relative_ranking": False,
        },
        "data": {"adjust_policy": "qfq", "source": "unified_fund_panel"},
        "frozen_gates": {
            "constructible_share_min": MIN_CONSTRUCTIBLE_SHARE,
            "common_calendar_retention_min": MIN_COMMON_CALENDAR_RETENTION,
            "staleness_days_max": MAX_STALENESS_CALENDAR_DAYS,
            "active_share_range": [MIN_ACTIVE_SHARE, MAX_ACTIVE_SHARE],
            "duplicate_and_invalid_rows": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记资产、信号与数据版本指纹，再读取基金面板。"""
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
        result = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """只构造趋势状态和目标预览，不执行收益计算。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*RISKY_ASSETS, DEFENSIVE_ASSET],
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    states = calculate_independent_trend_states(
        panel.adjusted_close,
        signals,
        RISKY_ASSETS,
        fast_window=FAST_WINDOW,
        slow_window=SLOW_WINDOW,
    )
    targets, _ = build_independent_trend_slot_targets(
        states,
        RISKY_ASSETS,
        DEFENSIVE_ASSET,
    )
    result = evaluate_feasibility(
        panel.coverage,
        panel.calendar,
        states,
        targets,
        signals,
        panel.latest_common_date,
        as_of_date,
    )
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["state_records"] = states.to_dict("records")
    result["reused"] = False
    return result


def evaluate_feasibility(
    coverage: list[dict[str, object]],
    calendar: list[pd.Timestamp],
    states: pd.DataFrame,
    targets: dict[str, dict[str, float]],
    signals: list[pd.Timestamp],
    latest_common_date: str,
    as_of_date: str,
) -> dict[str, Any]:
    """执行覆盖、新鲜度、完整截面和非退化状态门禁。"""
    expected_months = len(signals)
    constructible = len(targets)
    duplicate_rows = int(states.duplicated(["signal_date", "symbol"]).sum())
    numeric = states[["close", "ma60", "ma120"]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    invalid_rows = int((~np.isfinite(numeric)).any(axis=1).sum())
    active_share = {
        symbol: float(
            states.loc[
                states["symbol"].astype(str).eq(symbol),
                "trend_active",
            ].astype(bool).mean()
        )
        for symbol in RISKY_ASSETS
    }
    max_rows = max(int(item["row_count"]) for item in coverage)
    retention = len(calendar) / max_rows if max_rows else 0.0
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(latest_common_date)
    ).days
    complete_share = constructible / expected_months if expected_months else 0.0
    checks = {
        "all_assets_latest_same_date": (
            {str(item["end_date"]) for item in coverage}
            == {latest_common_date}
        ),
        "data_is_fresh": staleness <= MAX_STALENESS_CALENDAR_DAYS,
        "common_calendar_retention": (
            retention >= MIN_COMMON_CALENDAR_RETENTION
        ),
        "monthly_states_constructible": (
            complete_share >= MIN_CONSTRUCTIBLE_SHARE
        ),
        "states_are_not_degenerate": all(
            MIN_ACTIVE_SHARE <= ratio <= MAX_ACTIVE_SHARE
            for ratio in active_share.values()
        ),
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_invalid_rows": invalid_rows == 0,
    }
    return {
        "latest_common_date": latest_common_date,
        "staleness_days": int(staleness),
        "coverage": coverage,
        "signal_months": expected_months,
        "constructible_months": constructible,
        "constructible_share": complete_share,
        "common_calendar_retention": retention,
        "active_share": active_share,
        "duplicate_rows": duplicate_rows,
        "invalid_rows": invalid_rows,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """保存状态截面和可行性结论。"""
    states = pd.DataFrame(result.pop("state_records"))
    states_path = attempt.output_dir / "monthly_trend_states.csv"
    states.to_csv(states_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "五资产趋势状态覆盖、新鲜度和非退化门禁通过"
            if passed
            else "基金数据或趋势状态门禁未通过，回测前终止"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("trend_states", states_path, "月度趋势状态"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    parts: list[str] = []
    for label, path in [
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
