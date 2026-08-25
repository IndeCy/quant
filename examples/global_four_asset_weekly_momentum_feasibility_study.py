"""全球四资产周频20日相对动量的回测前数据门禁。"""

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
from examples import global_core_nasdaq_gold_four_asset_study as four_asset
from factors.etf_relative_strength import weekly_signal_dates
from factors.etf_weekly_relative_momentum import (
    build_top_momentum_targets,
    calculate_weekly_relative_momentum,
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


EXPERIMENT_ID = "global_four_asset_weekly_momentum_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/global-four-asset-weekly-momentum-data-feasibility-v1.md"
)
SYMBOLS = [
    four_asset.NASDAQ,
    four_asset.SP500,
    four_asset.GOLD,
    four_asset.BOND,
]
NAMES = {
    four_asset.NASDAQ: "纳斯达克100ETF",
    four_asset.SP500: "标普500ETF",
    four_asset.GOLD: "黄金ETF",
    four_asset.BOND: "5年国债ETF",
}
LOOKBACK_DAYS = 20
TOP_N = 2
LOAD_START = "20150713"
STUDY_START = "20160101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球四资产周频20日动量数据可行性 V1",
    category="data_feasibility",
    hypothesis="纳指、标普、黄金和国债能否形成新鲜完整且非退化的周频20日相对动量截面",
    definition={
        "universe": NAMES,
        "signal_preview": {
            "formula": "close_t/close_t_minus_20-1",
            "ranking": "descending",
            "frequency": "weekly_last_trading_day",
            "top_n": TOP_N,
            "future_holding_return_loaded": False,
        },
        "gates": {
            "common_days_min": 2600,
            "complete_week_share_min": 0.99,
            "staleness_days_max": 5,
            "selection_share_range": [0.10, 0.40],
            "invalid_or_duplicate_rows": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "weekly_global_momentum_feasibility_v1",
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
        data_version=four_asset._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, states, holdings = calculate(paths, as_of_date)
        complete_attempt(attempt, result, states, holdings)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        SYMBOLS,
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date
        for date in weekly_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
        and date < panel.calendar[-1]
    ]
    states = calculate_weekly_relative_momentum(
        panel.adjusted_close,
        signals,
        SYMBOLS,
        lookback_days=LOOKBACK_DAYS,
    )
    targets, holdings = build_top_momentum_targets(states, top_n=TOP_N)
    result = evaluate(
        panel,
        states,
        holdings,
        targets,
        signals,
        as_of_date,
    )
    report = paths.root / REPORT_PATH
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report)
    result["reused"] = False
    return result, states, holdings


def evaluate(
    panel,
    states: pd.DataFrame,
    holdings: pd.DataFrame,
    targets: dict[str, dict[str, float]],
    signals: list[pd.Timestamp],
    as_of_date: str,
) -> dict[str, Any]:
    counts = states.groupby("signal_date")["symbol"].nunique()
    complete = int(counts.eq(len(SYMBOLS)).sum())
    expected = len(signals)
    share = complete / expected if expected else 0.0
    duplicate_rows = int(states.duplicated(["signal_date", "symbol"]).sum())
    invalid_rows = int(
        (~np.isfinite(pd.to_numeric(states["momentum"], errors="coerce"))).sum()
    )
    selection = holdings["symbol"].value_counts(normalize=True)
    selection_share = {
        symbol: float(selection.get(symbol, 0.0))
        for symbol in SYMBOLS
    }
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)
    ).days
    checks = {
        "all_four_assets_present": (
            {str(item["symbol"]) for item in panel.coverage} == set(SYMBOLS)
        ),
        "common_days_at_least_2600": len(panel.calendar) >= 2600,
        "complete_week_share_at_least_99pct": share >= 0.99,
        "target_share_at_least_99pct": (
            len(targets) / expected if expected else 0.0
        )
        >= 0.99,
        "fresh_within_five_days": 0 <= staleness <= 5,
        "selection_share_between_10_and_40pct": (
            min(selection_share.values()) >= 0.10
            and max(selection_share.values()) <= 0.40
        ),
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_invalid_rows": invalid_rows == 0,
    }
    return {
        "latest_common_date": panel.latest_common_date,
        "common_days": len(panel.calendar),
        "expected_weeks": expected,
        "complete_weeks": complete,
        "complete_share": share,
        "constructible_targets": len(targets),
        "selection_share": selection_share,
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
    holdings: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    states_path = attempt.output_dir / "weekly_momentum_state_preview.csv"
    states.to_csv(states_path, index=False)
    holdings_path = attempt.output_dir / "weekly_selection_preview.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "全球四资产周频20日相对动量数据门禁通过"
            if passed
            else "全球四资产周频动量门禁未通过，收益回测前终止"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "数据可行性报告"),
            ExperimentArtifact("state_preview", states_path, "历史信号状态"),
            ExperimentArtifact(
                "selection_preview",
                holdings_path,
                "历史选择预览",
            ),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    shares = "\n".join(
        f"| {symbol} | {NAMES[symbol]} | {share:.1%} |"
        for symbol, share in result["selection_share"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 全球四资产周频20日动量数据可行性 V1

- 共同截止：{result['latest_common_date']}；共同日：{result['common_days']}。
- 完整周：{result['complete_weeks']}/{result['expected_weeks']}
  ({result['complete_share']:.2%})。
- 本阶段仅计算信号日前20日收益与Top2预览，不读取下一周收益。

| 代码 | 资产 | Top2入选占比 |
|---|---|---:|
{shares}

## 冻结门禁

{checks}

结论：`{result['decision']}`。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260728")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
