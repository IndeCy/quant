"""A股宽基与行业ETF周频短期反转的回测前数据门禁。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import FundPortfolioPanel, load_fund_portfolio_panel
from factors.etf_relative_strength import weekly_signal_dates
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "a_share_etf_weekly_reversal_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/a-share-etf-weekly-reversal-data-feasibility-v1.md"
)
ETF_NAMES = {
    "510050.SH": "上证50ETF",
    "510300.SH": "沪深300ETF",
    "510500.SH": "中证500ETF",
    "512100.SH": "中证1000ETF",
    "159915.SZ": "创业板ETF",
    "510880.SH": "红利ETF",
    "512880.SH": "证券ETF",
    "512800.SH": "银行ETF",
    "512660.SH": "军工ETF",
    "159928.SZ": "消费ETF",
    "512010.SH": "医药ETF",
    "512400.SH": "有色ETF",
}
ETF_SYMBOLS = list(ETF_NAMES)
LOAD_START = "20180101"
STUDY_START = "20190101"
LOOKBACK_DAYS = 5
MIN_COMMON_DAYS = 1800
MIN_WEEKLY_CONSTRUCTIBLE_SHARE = 0.98
MIN_MEDIAN_AMOUNT = 30_000.0
MAX_STALENESS_DAYS = 5
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="A股ETF周频短期反转数据可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "固定12只高流动性宽基与行业ETF能否形成无缺口、可成交的5日反转周频截面"
    ),
    definition={
        "universe": ETF_NAMES,
        "universe_selection": (
            "listed_before_2019_and_recent_average_amount_above_50m_in_source_scan"
        ),
        "signal_preview": {
            "formula": "close_t/close_t_minus_5-1",
            "frequency": "last_trading_day_of_week",
            "ranking": "ascending",
            "future_return_loading": False,
        },
        "frozen_gates": {
            "minimum_common_days": MIN_COMMON_DAYS,
            "weekly_constructible_share_min": MIN_WEEKLY_CONSTRUCTIBLE_SHARE,
            "median_daily_amount_min": MIN_MEDIAN_AMOUNT,
            "staleness_days_max": MAX_STALENESS_DAYS,
            "duplicate_or_invalid_rows": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "weekly_cross_section_feasibility_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记数据门禁，再读取价格和成交额，不计算持有期收益。"""
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
        result, states = calculate(paths, as_of_date)
        complete_attempt(attempt, result, states)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """仅生成截至信号日的5日收益状态与数据质量统计。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        ETF_SYMBOLS,
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date
        for date in weekly_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
        and date < panel.calendar[-1]
    ]
    trailing = (
        panel.adjusted_close[ETF_SYMBOLS]
        / panel.adjusted_close[ETF_SYMBOLS].shift(LOOKBACK_DAYS)
        - 1.0
    )
    rows: list[dict[str, object]] = []
    for date in signals:
        if date not in trailing.index:
            continue
        values = trailing.loc[date]
        for symbol in ETF_SYMBOLS:
            value = values[symbol]
            if pd.notna(value):
                rows.append(
                    {
                        "signal_date": date.strftime("%Y%m%d"),
                        "symbol": symbol,
                        "return_5d": float(value),
                    }
                )
    states = pd.DataFrame(rows)
    result = evaluate_feasibility(panel, states, signals, as_of_date)
    report = paths.root / REPORT_PATH
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report)
    result["reused"] = False
    return result, states


def evaluate_feasibility(
    panel: FundPortfolioPanel,
    states: pd.DataFrame,
    signals: list[pd.Timestamp],
    as_of_date: str,
) -> dict[str, Any]:
    """检查共同日历、完整截面、新鲜度、成交额和无效记录。"""
    dates = states.groupby("signal_date")["symbol"].nunique()
    complete_weeks = int(dates.eq(len(ETF_SYMBOLS)).sum())
    expected_weeks = len(signals)
    constructible_share = (
        complete_weeks / expected_weeks if expected_weeks else 0.0
    )
    bars = panel.bars.reset_index()
    bars = bars[bars["date"].ge(pd.Timestamp(STUDY_START))]
    liquidity = {
        symbol: float(
            pd.to_numeric(
                bars.loc[bars["symbol"].eq(symbol), "amount"],
                errors="coerce",
            ).median()
        )
        for symbol in ETF_SYMBOLS
    }
    duplicate_rows = int(states.duplicated(["signal_date", "symbol"]).sum())
    invalid_rows = int(
        (~np.isfinite(pd.to_numeric(states["return_5d"], errors="coerce"))).sum()
    )
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)
    ).days
    covered = {str(item["symbol"]) for item in panel.coverage}
    checks = {
        "all_twelve_assets_present": covered == set(ETF_SYMBOLS),
        "all_assets_listed_before_study": all(
            str(item["start_date"]) < STUDY_START
            for item in panel.coverage
        ),
        "common_days_at_least_1800": len(panel.calendar) >= MIN_COMMON_DAYS,
        "weekly_constructible_share_at_least_98pct": (
            constructible_share >= MIN_WEEKLY_CONSTRUCTIBLE_SHARE
        ),
        "all_median_amount_at_least_30000": all(
            value >= MIN_MEDIAN_AMOUNT for value in liquidity.values()
        ),
        "data_fresh_within_five_days": 0 <= staleness <= MAX_STALENESS_DAYS,
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_invalid_rows": invalid_rows == 0,
    }
    return {
        "latest_common_date": panel.latest_common_date,
        "common_days": len(panel.calendar),
        "expected_weeks": expected_weeks,
        "complete_weeks": complete_weeks,
        "constructible_share": constructible_share,
        "median_amount": liquidity,
        "staleness_days": int(staleness),
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


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    states: pd.DataFrame,
) -> None:
    """保存门禁报告与状态预览，不保存未来收益。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    state_path = attempt.output_dir / "weekly_signal_preview.csv"
    states.to_csv(state_path, index=False)
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "12只ETF共同覆盖、流动性和周频截面门禁通过"
            if passed
            else "ETF数据门禁未通过，收益回测前终止"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "数据可行性报告"),
            ExperimentArtifact(
                "signal_preview",
                state_path,
                "仅含信号日历史状态的预览",
            ),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    liquidity = "\n".join(
        f"| {symbol} | {ETF_NAMES[symbol]} | {value:,.0f} |"
        for symbol, value in result["median_amount"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# A股ETF周频短期反转数据可行性 V1

- 数据共同截止：{result['latest_common_date']}。
- 共同交易日：{result['common_days']}。
- 完整周截面：{result['complete_weeks']}/{result['expected_weeks']}
  ({result['constructible_share']:.2%})。
- 本阶段只计算信号日向后看5日收益，不读取持有期收益、不执行回测。

| 代码 | 名称 | 2019后日成交额中位数（源字段单位） |
|---|---|---:|
{liquidity}

## 冻结门禁

{checks}

结论：`{result['decision']}`。
"""


def data_version(paths: RuntimePaths) -> str:
    return equal_data_version(paths)


def equal_data_version(paths: RuntimePaths) -> str:
    parts = []
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
