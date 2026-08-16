"""标普500、黄金、国债固定等权组合的回测前数据门禁。"""

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
from examples.global_defensive_equal_feasibility_report import render_report
from factors.etf_momentum import month_end_signal_dates
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "global_defensive_equal_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/global-defensive-equal-data-feasibility-v1.md"
)
ASSETS = ["513500.SH", "518880.SH", "511010.SH"]
LOAD_START = "20140101"
STUDY_START = "20150101"
MIN_CONSTRUCTIBLE_SHARE = 0.98
MIN_COMMON_CALENDAR_RETENTION = 0.90
MIN_MONTH_END_AMOUNT_RMB = 10_000_000.0
MAX_STALENESS_CALENDAR_DAYS = 10
MAX_ABSOLUTE_DAILY_RETURN = 0.40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球防守三资产等权数据可行性 V1",
    category="data_feasibility",
    hypothesis="标普500、黄金和国债能否用统一qfq历史构造可交易的独立配置资产",
    definition={
        "asset_pool": {
            "513500.SH": "sp500_equity",
            "518880.SH": "gold",
            "511010.SH": "five_year_government_bond",
            "roles_fixed_before_return_scan": True,
        },
        "portfolio_preview": {
            "weight": "one_third_each",
            "rebalance": "monthly",
        },
        "data": {
            "source": "unified_fund_panel",
            "adjust_policy": "qfq",
            "study_start": STUDY_START,
        },
        "frozen_gates": {
            "history_start_by": "20141231",
            "constructible_share_min": MIN_CONSTRUCTIBLE_SHARE,
            "common_calendar_retention_min": (
                MIN_COMMON_CALENDAR_RETENTION
            ),
            "monthly_amount_median_min_rmb": (
                MIN_MONTH_END_AMOUNT_RMB
            ),
            "staleness_days_max": MAX_STALENESS_CALENDAR_DAYS,
            "absolute_daily_return_max": MAX_ABSOLUTE_DAILY_RETURN,
            "duplicate_invalid_jump_violations": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "fixed_asset_roles_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在读取基金大表前登记冻结定义和数据指纹。"""
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
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, Any]:
    """仅物化共同日历和月末成交额，不计算资产或组合收益。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        ASSETS,
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    monthly = build_monthly_liquidity(panel)
    result = evaluate_feasibility(panel, monthly, as_of_date)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def build_monthly_liquidity(
    panel: FundPortfolioPanel,
) -> pd.DataFrame:
    """读取可执行信号日成交额，排除没有下一交易日的未完成月份。"""
    bars = panel.bars.reset_index().copy()
    bars["date"] = pd.to_datetime(bars["date"])
    signal_dates = {
        pd.Timestamp(value)
        for value in month_end_signal_dates(panel.calendar)
        if value >= pd.Timestamp(STUDY_START)
    }
    monthly = bars[bars["date"].isin(signal_dates)].copy()
    monthly["signal_date"] = monthly["date"].dt.strftime("%Y%m%d")
    monthly["amount_rmb"] = (
        pd.to_numeric(monthly["amount"], errors="coerce") * 1000.0
    )
    return monthly[
        ["signal_date", "symbol", "amount_rmb"]
    ].sort_values(["signal_date", "symbol"]).reset_index(drop=True)


def evaluate_feasibility(
    panel: FundPortfolioPanel,
    monthly: pd.DataFrame,
    as_of_date: str,
) -> dict[str, Any]:
    """执行历史、共同日历、流动性和价格完整性门禁。"""
    bars = panel.bars.reset_index()
    duplicate_rows = int(
        bars.duplicated(["date", "symbol"]).sum()
    )
    numeric = bars[
        ["open", "high", "low", "close", "volume", "amount", "adj_factor"]
    ].apply(pd.to_numeric, errors="coerce")
    invalid_rows = int(
        ((~np.isfinite(numeric)).any(axis=1) | numeric["close"].le(0)).sum()
    )
    daily_returns = panel.adjusted_close.pct_change(fill_method=None)
    jump_violations = int(
        daily_returns.abs().gt(MAX_ABSOLUTE_DAILY_RETURN).sum().sum()
    )
    expected_signals = [
        value
        for value in month_end_signal_dates(panel.calendar)
        if value >= pd.Timestamp(STUDY_START)
    ]
    complete_months = int(
        monthly.groupby("signal_date")["symbol"].nunique().eq(
            len(ASSETS)
        ).sum()
    )
    expected_months = len(expected_signals)
    constructible_share = (
        complete_months / expected_months if expected_months else 0.0
    )
    max_rows = max(
        int(item["row_count"]) for item in panel.coverage
    )
    calendar_retention = (
        len(panel.calendar) / max_rows if max_rows else 0.0
    )
    staleness = (
        pd.Timestamp(as_of_date)
        - pd.Timestamp(panel.latest_common_date)
    ).days
    liquidity = {
        symbol: {
            "median_month_end_amount_rmb": float(
                monthly.loc[
                    monthly["symbol"].astype(str).eq(symbol),
                    "amount_rmb",
                ].median()
            ),
            "minimum_month_end_amount_rmb": float(
                monthly.loc[
                    monthly["symbol"].astype(str).eq(symbol),
                    "amount_rmb",
                ].min()
            ),
        }
        for symbol in ASSETS
    }
    checks = {
        "all_assets_history_starts_before_2015": all(
            str(item["start_date"]) <= "20141231"
            for item in panel.coverage
        ),
        "all_assets_latest_same_date": (
            {str(item["end_date"]) for item in panel.coverage}
            == {panel.latest_common_date}
        ),
        "data_is_fresh": staleness <= MAX_STALENESS_CALENDAR_DAYS,
        "common_calendar_retention": (
            calendar_retention >= MIN_COMMON_CALENDAR_RETENTION
        ),
        "monthly_portfolio_constructible": (
            constructible_share >= MIN_CONSTRUCTIBLE_SHARE
        ),
        "all_assets_liquid": all(
            values["median_month_end_amount_rmb"]
            >= MIN_MONTH_END_AMOUNT_RMB
            for values in liquidity.values()
        ),
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_invalid_rows": invalid_rows == 0,
        "zero_adjusted_price_jump_violations": jump_violations == 0,
    }
    passed = all(checks.values())
    return {
        "latest_common_date": panel.latest_common_date,
        "staleness_days": int(staleness),
        "coverage": panel.coverage,
        "signal_months": expected_months,
        "constructible_months": complete_months,
        "constructible_share": constructible_share,
        "common_calendar_retention": calendar_retention,
        "liquidity": liquidity,
        "duplicate_rows": duplicate_rows,
        "invalid_rows": invalid_rows,
        "jump_violations": jump_violations,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_FIXED_MULTIFOLD_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """保存数据门禁和月末流动性，不保存任何收益。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monthly_path = attempt.output_dir / "monthly_liquidity.csv"
    pd.DataFrame(result["monthly_records"]).to_csv(
        monthly_path,
        index=False,
    )
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "全球防守三资产覆盖、复权与流动性门禁通过"
            if passed
            else "全球防守三资产数据门禁未通过，收益回测前终止"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact(
                "monthly_liquidity",
                monthly_path,
                "月末成交额覆盖",
            ),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定基金基线与增量文件版本。"""
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
