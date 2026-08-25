"""五只A股科技ETF周频5日反转的回测前数据门禁。"""

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
from examples import a_share_tech_etf_rotation_study as tech
from factors.etf_relative_strength import weekly_signal_dates
from factors.etf_short_term_reversal import calculate_weekly_reversal_states
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "a_share_tech_etf_weekly_reversal_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/a-share-tech-etf-weekly-reversal-data-feasibility-v1.md"
)
LOOKBACK_DAYS = 5
MIN_COMMON_DAYS = 1600
MIN_COMPLETE_SHARE = 0.99
MIN_MEDIAN_AMOUNT = 30_000.0
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="A股科技ETF周频5日反转数据可行性 V1",
    category="data_feasibility",
    hypothesis="固定五只科技ETF能否形成新鲜、完整且可成交的周频5日弱势排名截面",
    definition={
        "universe": tech.TECH_NAMES,
        "signal_preview": {
            "formula": "close_t/close_t_minus_5-1",
            "frequency": "weekly_last_trading_day",
            "ranking": "ascending_weakest_first",
            "future_holding_return_loaded": False,
        },
        "gates": {
            "common_days_min": MIN_COMMON_DAYS,
            "complete_week_share_min": MIN_COMPLETE_SHARE,
            "median_amount_min": MIN_MEDIAN_AMOUNT,
            "staleness_days_max": 5,
            "invalid_or_duplicate_rows": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "tech_weekly_reversal_feasibility_v1",
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
        data_version=tech._data_version(paths),
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
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        tech.TECH_SYMBOLS,
        start_date=tech.LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date
        for date in weekly_signal_dates(panel.calendar)
        if date >= pd.Timestamp(tech.STUDY_START)
        and date < panel.calendar[-1]
    ]
    states = calculate_weekly_reversal_states(
        panel.adjusted_close,
        signals,
        tech.TECH_SYMBOLS,
        lookback_days=LOOKBACK_DAYS,
    )
    result = evaluate(panel, states, signals, as_of_date)
    report = paths.root / REPORT_PATH
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report)
    result["reused"] = False
    return result, states


def evaluate(
    panel,
    states: pd.DataFrame,
    signals: list[pd.Timestamp],
    as_of_date: str,
    *,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    universe = list(symbols or tech.TECH_SYMBOLS)
    counts = states.groupby("signal_date")["symbol"].nunique()
    complete = int(counts.eq(len(universe)).sum())
    expected = len(signals)
    share = complete / expected if expected else 0.0
    bars = panel.bars.reset_index()
    bars = bars[bars["date"].ge(pd.Timestamp(tech.STUDY_START))]
    median_amount = {
        symbol: float(
            pd.to_numeric(
                bars.loc[bars["symbol"].eq(symbol), "amount"],
                errors="coerce",
            ).median()
        )
        for symbol in universe
    }
    duplicate_rows = int(states.duplicated(["signal_date", "symbol"]).sum())
    invalid_rows = int(
        (~np.isfinite(pd.to_numeric(states["return_5d"], errors="coerce"))).sum()
    )
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)
    ).days
    checks = {
        "all_assets_present": (
            {str(item["symbol"]) for item in panel.coverage}
            == set(universe)
        ),
        "common_days_at_least_1600": len(panel.calendar) >= MIN_COMMON_DAYS,
        "complete_week_share_at_least_99pct": share >= MIN_COMPLETE_SHARE,
        "all_median_amount_at_least_30000": all(
            value >= MIN_MEDIAN_AMOUNT for value in median_amount.values()
        ),
        "fresh_within_five_days": 0 <= staleness <= 5,
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_invalid_rows": invalid_rows == 0,
    }
    return {
        "latest_common_date": panel.latest_common_date,
        "common_days": len(panel.calendar),
        "expected_weeks": expected,
        "complete_weeks": complete,
        "complete_share": share,
        "median_amount": median_amount,
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
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    states_path = attempt.output_dir / "weekly_reversal_state_preview.csv"
    states.to_csv(states_path, index=False)
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "五只科技ETF周频反转截面数据门禁通过"
            if passed
            else "五只科技ETF周频反转数据门禁未通过，回测前终止"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "数据可行性报告"),
            ExperimentArtifact(
                "state_preview",
                states_path,
                "仅含历史信号状态的预览",
            ),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {symbol} | {tech.TECH_NAMES[symbol]} | {value:,.0f} |"
        for symbol, value in result["median_amount"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# A股科技ETF周频5日反转数据可行性 V1

- 共同截止：{result['latest_common_date']}；共同交易日：{result['common_days']}。
- 完整周截面：{result['complete_weeks']}/{result['expected_weeks']}
  ({result['complete_share']:.2%})。
- 仅生成信号日向后看5日收益排名，不读取下一周收益。

| 代码 | 名称 | 2020后日成交额中位数（源字段单位） |
|---|---|---:|
{rows}

## 冻结门禁

{checks}

结论：`{result['decision']}`。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=tech.RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
