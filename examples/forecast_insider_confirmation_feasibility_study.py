"""业绩预告与重要股东净增持交互因子的点时覆盖审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.forecast_events import (
    ForecastEventPaths,
    attach_forecast_database,
    create_forecast_signal_date_table,
    materialize_forecast_event_asof,
)
from data.holder_trades import (
    attach_holder_trade_database,
    create_holder_trade_signal_date_table,
    materialize_holder_trade_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from examples.earnings_forecast_momentum_study import load_forecast_candidates
from examples.insider_net_buying_study import load_holder_trade_candidates
from factors.earnings_forecast import score_earnings_forecast_frame
from factors.insider_net_buying import score_insider_net_buying_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "forecast_insider_confirmation_feasibility_v1"
REPORT_PATH = Path("docs/research/forecast-insider-confirmation-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
FORECAST_LOOKBACK_DAYS = 90
INSIDER_LOOKBACK_DAYS = 180
TARGET_SIZE = 10
MIN_YEARS_WITH_OVERLAP = 8
MIN_NONEMPTY_MONTHS = 24
MIN_MEDIAN_OVERLAP = 10
MIN_LOCKED_CONSTRUCTIBLE_SHARE = 0.50

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="业绩预告与增持确认交互可行性 V1",
    category="data_feasibility",
    hypothesis="正向业绩预告经过重要股东净增持确认后，是否仍有足够覆盖进入月频研究",
    definition={
        "inputs": {
            "forecast_factor": "earnings_forecast_momentum_v1",
            "insider_factor": "insider_net_buying_v1",
            "combination": "point_in_time_intersection",
        },
        "visibility": {
            "forecast_lookback_calendar_days": FORECAST_LOOKBACK_DAYS,
            "holder_trade_lookback_calendar_days": INSIDER_LOOKBACK_DAYS,
            "announcement_date_lte_signal_date": True,
        },
        "sampling": {
            "start": STUDY_START,
            "frequency": "month_end",
            "target_size": TARGET_SIZE,
        },
        "frozen_feasibility_gates": {
            "years_with_overlap_at_least": MIN_YEARS_WITH_OVERLAP,
            "nonempty_months_at_least": MIN_NONEMPTY_MONTHS,
            "monthly_overlap_median_at_least": MIN_MEDIAN_OVERLAP,
            "locked_years_have_no_zero_overlap_year": True,
            "locked_top10_constructible_share_at_least": (
                MIN_LOCKED_CONSTRUCTIBLE_SHARE
            ),
        },
        "decision": "feasibility_only_no_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先申请研究指纹，再扫描两个事件缓存。"""
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
    """构造两个独立 as-of 候选集，并只统计同月同股票交集。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_forecast_signal_date_table(connection, signal_dates)
        create_holder_trade_signal_date_table(connection, signal_dates)
        attach_forecast_database(connection, ForecastEventPaths(paths.forecast_path))
        attach_holder_trade_database(connection, paths.holder_trade_path)
        materialize_forecast_event_asof(
            connection,
            lookback_days=FORECAST_LOOKBACK_DAYS,
        )
        materialize_holder_trade_asof(
            connection,
            lookback_days=INSIDER_LOOKBACK_DAYS,
        )
        forecast = load_forecast_candidates(connection)
        insider = load_holder_trade_candidates(connection)
    finally:
        connection.close()

    monthly = build_monthly_overlap(signal_dates, forecast, insider)
    result = evaluate_feasibility(monthly, latest_date)
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["reused"] = False
    result["monthly_records"] = monthly.to_dict("records")
    return result


def build_monthly_overlap(
    signal_dates: list[str],
    forecast_candidates: pd.DataFrame,
    insider_candidates: pd.DataFrame,
) -> pd.DataFrame:
    """逐月应用原因子有效性规则，避免把无效原始事件计入交集。"""
    rows: list[dict[str, Any]] = []
    forecast_dates = forecast_candidates["signal_date"].astype(str)
    insider_dates = insider_candidates["signal_date"].astype(str)
    for signal_date in signal_dates:
        forecast_group = forecast_candidates[forecast_dates.eq(signal_date)]
        insider_group = insider_candidates[insider_dates.eq(signal_date)]
        forecast_scored = score_earnings_forecast_frame(forecast_group)
        insider_scored = score_insider_net_buying_frame(insider_group)
        forecast_symbols = set(forecast_scored["symbol"].astype(str))
        insider_symbols = set(insider_scored["symbol"].astype(str))
        overlap = sorted(forecast_symbols & insider_symbols)
        rows.append(
            {
                "signal_date": signal_date,
                "year": int(signal_date[:4]),
                "forecast_count": len(forecast_symbols),
                "insider_count": len(insider_symbols),
                "overlap_count": len(overlap),
                "top10_constructible": len(overlap) >= TARGET_SIZE,
                "overlap_symbols": ",".join(overlap),
            }
        )
    return pd.DataFrame(rows)


def evaluate_feasibility(monthly: pd.DataFrame, latest_date: str) -> dict[str, Any]:
    """按预先冻结的门槛判断是否值得进入回测。"""
    if monthly.empty:
        raise ValueError("没有可审计的月末信号日")
    overlap = monthly["overlap_count"].astype(int)
    years_with_overlap = int(monthly.loc[overlap.gt(0), "year"].nunique())
    nonempty_months = int(overlap.gt(0).sum())
    median_overlap = float(overlap.median())
    locked = monthly[monthly["signal_date"].ge(LOCKED_START)].copy()
    locked_year_counts = locked.groupby("year")["overlap_count"].sum()
    locked_no_zero_year = bool(
        not locked_year_counts.empty and locked_year_counts.gt(0).all()
    )
    locked_constructible_share = float(
        locked["top10_constructible"].mean() if not locked.empty else 0.0
    )
    checks = {
        "years_with_overlap": years_with_overlap >= MIN_YEARS_WITH_OVERLAP,
        "nonempty_months": nonempty_months >= MIN_NONEMPTY_MONTHS,
        "median_overlap": median_overlap >= MIN_MEDIAN_OVERLAP,
        "locked_no_zero_overlap_year": locked_no_zero_year,
        "locked_top10_constructible_share": (
            locked_constructible_share >= MIN_LOCKED_CONSTRUCTIBLE_SHARE
        ),
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "years_with_overlap": years_with_overlap,
        "nonempty_months": nonempty_months,
        "median_overlap": median_overlap,
        "maximum_overlap": int(overlap.max()),
        "top10_constructible_months": int(monthly["top10_constructible"].sum()),
        "locked_signal_months": int(len(locked)),
        "locked_constructible_share": locked_constructible_share,
        "locked_year_overlap_counts": {
            str(year): int(count) for year, count in locked_year_counts.items()
        },
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """保存月度覆盖明细与结论，防止以后重复扫描同一组合。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_overlap.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "覆盖门槛全部通过，可进入固定定义回测"
            if passed
            else "事件交集覆盖不足，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "交互因子可行性报告"),
            ExperimentArtifact("monthly_overlap", monthly_path, "月度事件交集"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """输出不包含收益结论的覆盖审计报告。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 业绩预告 × 重要股东净增持交互可行性 V1

- 数据截止：{result['latest_date']}，月末截面：{result['signal_months']} 个。
- 有交集年份：{result['years_with_overlap']}，非空月份：
  {result['nonempty_months']}。
- 月度交集中位数：{result['median_overlap']:.1f}，最大：
  {result['maximum_overlap']}。
- 可完整构造 Top10：{result['top10_constructible_months']} 个月。
- 2022 年后可构造 Top10 比例：
  {result['locked_constructible_share']:.2%}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段没有运行收益回测，也没有注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """用两个事件库及行情库状态绑定本次覆盖扫描。"""
    parts: list[str] = []
    for label, path in [
        ("forecast", paths.forecast_path),
        ("holder_trade", paths.holder_trade_path),
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
