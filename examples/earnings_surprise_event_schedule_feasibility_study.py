"""SUE 事件驱动调仓日历的固定可行性研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.earnings_surprise_data_feasibility_study import (
    FOLDS,
    TOP_N,
    build_diagnostics,
    load_feasibility_data,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "earnings_surprise_event_schedule_feasibility_v2"
REPORT_PATH = Path(
    "docs/research/earnings-surprise-event-schedule-feasibility-v2.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="SUE 事件驱动调仓日历可行性 V2",
    category="data_feasibility",
    hypothesis="只在新鲜SUE候选足够时重选、其余月份持有不动，能否形成稳定事件调仓日历",
    definition={
        "factor_definition": (
            "same_as_earnings_surprise_data_feasibility_v1"
        ),
        "schedule": {
            "rebalance_when_candidate_count_at_least": TOP_N,
            "otherwise": "carry_previous_target_without_rescoring",
            "maximum_consecutive_skipped_months": 2,
        },
        "frozen_gate": {
            "data_integrity_same_as_v1": True,
            "event_month_share_min": 0.85,
            "each_fold_event_month_share_min": 0.80,
            "maximum_consecutive_skipped_months": 2,
            "minimum_rebalance_months_per_full_year": 8,
            "first_rebalance_by": "20150331",
        },
        "feasibility_only_no_returns": True,
        "parameters_fixed_before_data_read": True,
        "methodology_version": "sue_event_schedule_v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """研究门禁通过后才读取完整SUE月度覆盖。"""
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
        result, monthly = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, monthly)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """检查事件重选月份、连续空窗和年度覆盖。"""
    latest_date, candidates, monthly = load_feasibility_data(
        paths,
        as_of_date,
    )
    base = build_diagnostics(candidates, monthly)
    schedule = build_schedule_diagnostics(monthly)
    gate = evaluate_schedule(base, schedule)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(base, schedule, gate, latest_date),
        encoding="utf-8",
    )
    return {
        "experiment_id": EXPERIMENT_ID,
        "latest_date": latest_date,
        "base_diagnostics": base,
        "schedule_diagnostics": schedule,
        "gate": gate,
        "decision": (
            "EVENT_BACKTEST_ALLOWED"
            if gate["passed"]
            else "STOP_BEFORE_BACKTEST"
        ),
        "report_path": str(report_path),
        "reused": False,
    }, monthly


def build_schedule_diagnostics(monthly: pd.DataFrame) -> dict[str, Any]:
    """量化持有沿用方案的事件月份覆盖。"""
    frame = monthly.sort_values("signal_date").copy()
    frame["year"] = frame["signal_date"].astype(str).str[:4]
    full_years = frame.groupby("year").size()
    complete_years = set(full_years[full_years >= 12].index)
    yearly = (
        frame[frame["year"].isin(complete_years)]
        .groupby("year")["constructible"]
        .sum()
    )
    first = frame.loc[frame["constructible"], "signal_date"]
    return {
        "event_month_share": float(frame["constructible"].mean()),
        "max_consecutive_skipped_months": max_false_run(
            frame["constructible"]
        ),
        "first_rebalance_date": str(first.iloc[0]) if not first.empty else "",
        "minimum_rebalance_months_per_full_year": (
            int(yearly.min()) if not yearly.empty else 0
        ),
        "rebalance_months_by_year": {
            str(year): int(value) for year, value in yearly.items()
        },
    }


def max_false_run(values: pd.Series) -> int:
    """计算最长连续不可构造月份。"""
    longest = 0
    current = 0
    for value in values.astype(bool):
        current = 0 if value else current + 1
        longest = max(longest, current)
    return longest


def evaluate_schedule(
    base: dict[str, Any],
    schedule: dict[str, Any],
) -> dict[str, Any]:
    """执行事件日历研究前冻结的门槛。"""
    data_clean = (
        base["asof_violations"] == 0
        and base["event_age_violations"] == 0
        and base["history_observation_violations"] == 0
        and base["duplicate_signal_symbol"] == 0
    )
    checks = {
        "data_integrity": data_clean,
        "event_month_share_at_least_85pct": (
            schedule["event_month_share"] >= 0.85
        ),
        "each_fold_event_share_at_least_80pct": all(
            value >= 0.80
            for value in base["fold_constructible_share"].values()
        ),
        "at_most_two_consecutive_skipped_months": (
            schedule["max_consecutive_skipped_months"] <= 2
        ),
        "at_least_eight_rebalances_per_full_year": (
            schedule["minimum_rebalance_months_per_full_year"] >= 8
        ),
        "first_rebalance_by_20150331": (
            bool(schedule["first_rebalance_date"])
            and schedule["first_rebalance_date"] <= "20150331"
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def render_report(
    base: dict[str, Any],
    schedule: dict[str, Any],
    gate: dict[str, Any],
    latest_date: str,
) -> str:
    """输出事件调仓日历可行性报告。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    years = "\n".join(
        f"- {year}：{count}次"
        for year, count in schedule[
            "rebalance_months_by_year"
        ].items()
    )
    return f"""# SUE 事件驱动调仓日历可行性 V2

- 数据截止：{latest_date}。
- 可重选月份占比：{schedule['event_month_share']:.2%}。
- 最长连续沿用持仓：{schedule['max_consecutive_skipped_months']}个月。
- 首次可重选日期：{schedule['first_rebalance_date']}。
- 完整年度最少重选次数：
  {schedule['minimum_rebalance_months_per_full_year']}。

## 完整年度重选次数

{years}

## 固定门槛

{checks}

结论：{'允许按事件调仓定义进入回测' if gate['passed'] else '事件日历仍不稳定，停止于回测前'}。
"""


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    monthly: pd.DataFrame,
) -> None:
    """归档新调仓定义，不覆盖V1失败记录。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    calendar_path = attempt.output_dir / "event_calendar.csv"
    monthly.to_csv(calendar_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "事件月份覆盖稳定，允许进入冻结定义回测"
            if passed
            else "事件调仓日历仍不稳定，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "事件日历报告"),
            ExperimentArtifact(
                "event_calendar",
                calendar_path,
                "月度事件调仓日历",
            ),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    files = [
        paths.income_statement_path,
        paths.base_market_path,
        paths.live_market_increment_path,
    ]
    return "|".join(
        f"{path.name}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for path in files
    )


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
