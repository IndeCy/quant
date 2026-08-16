"""半导体ETF、黄金和5年国债固定三等权的数据门禁。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples import a_share_tech_etf_rotation_study as tech
from examples import global_defensive_equal_study as global_core
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


EXPERIMENT_ID = "china_semiconductor_gold_bond_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/china-semiconductor-gold-bond-data-feasibility-v1.md"
)
SEMICONDUCTOR = "512480.SH"
GOLD = global_core.GOLD_SYMBOL
BOND = global_core.BOND_SYMBOL
SYMBOLS = [SEMICONDUCTOR, GOLD, BOND]
NAMES = {
    SEMICONDUCTOR: "半导体ETF",
    GOLD: "黄金ETF",
    BOND: "5年国债ETF",
}
LOAD_START = "20190823"
STUDY_START = "20200101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="半导体黄金国债三资产数据可行性 V1",
    category="data_feasibility",
    hypothesis="半导体成长、黄金和国债能否形成新鲜、完整、流动且低相关的月频三资产面板",
    definition={
        "assets": NAMES,
        "portfolio_preview": {
            "weights": {symbol: 1 / 3 for symbol in SYMBOLS},
            "rebalance": "monthly",
            "return_backtest": False,
        },
        "gates": {
            "common_days_min": 1600,
            "monthly_signals_min": 75,
            "staleness_days_max": 5,
            "median_amount_min": 100_000.0,
            "maximum_pairwise_correlation": 0.60,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "semiconductor_three_asset_feasibility_v1",
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
        result, correlations = calculate(paths, as_of_date)
        complete_attempt(attempt, result, correlations)
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
        SYMBOLS,
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    correlations = (
        panel.adjusted_close[SYMBOLS]
        .pct_change(fill_method=None)
        .corr()
    )
    pairwise = [
        abs(float(correlations.loc[left, right]))
        for index, left in enumerate(SYMBOLS)
        for right in SYMBOLS[index + 1 :]
    ]
    bars = panel.bars.reset_index()
    bars = bars[bars["date"].ge(pd.Timestamp(STUDY_START))]
    median_amount = {
        symbol: float(
            pd.to_numeric(
                bars.loc[bars["symbol"].eq(symbol), "amount"],
                errors="coerce",
            ).median()
        )
        for symbol in SYMBOLS
    }
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)
    ).days
    checks = {
        "all_three_assets_present": (
            {str(item["symbol"]) for item in panel.coverage} == set(SYMBOLS)
        ),
        "common_days_at_least_1600": len(panel.calendar) >= 1600,
        "monthly_signals_at_least_75": len(signals) >= 75,
        "fresh_within_five_days": 0 <= staleness <= 5,
        "all_median_amount_at_least_100000": all(
            value >= 100_000.0 for value in median_amount.values()
        ),
        "pairwise_correlation_at_most_060": max(pairwise) <= 0.60,
        "no_duplicate_dates": not panel.adjusted_close.index.duplicated().any(),
        "all_prices_positive": bool(panel.adjusted_close.gt(0).all().all()),
    }
    result = {
        "latest_common_date": panel.latest_common_date,
        "common_days": len(panel.calendar),
        "monthly_signals": len(signals),
        "median_amount": median_amount,
        "correlations": {
            left: {
                right: float(correlations.loc[left, right])
                for right in SYMBOLS
            }
            for left in SYMBOLS
        },
        "maximum_absolute_pairwise_correlation": max(pairwise),
        "staleness_days": int(staleness),
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, correlations


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    correlations: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    correlations_path = attempt.output_dir / "asset_correlations.csv"
    correlations.to_csv(correlations_path)
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "半导体黄金国债共同覆盖、流动性和相关性门禁通过"
            if passed
            else "半导体三资产数据门禁未通过，收益回测前终止"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "数据可行性报告"),
            ExperimentArtifact(
                "correlations",
                correlations_path,
                "资产相关性",
            ),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    liquidity = "\n".join(
        f"| {symbol} | {NAMES[symbol]} | {value:,.0f} |"
        for symbol, value in result["median_amount"].items()
    )
    correlations = "\n".join(
        f"| {left} | {right} | {value:.3f} |"
        for left, row in result["correlations"].items()
        for right, value in row.items()
        if left < right
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 半导体黄金国债三资产数据可行性 V1

- 共同截止：{result['latest_common_date']}；共同日：{result['common_days']}。
- 2020后月末信号：{result['monthly_signals']}。
- 仅检查数据、流动性和同期相关性，不计算组合收益。

| 代码 | 资产 | 日成交额中位数（源字段单位） |
|---|---|---:|
{liquidity}

| 资产A | 资产B | 日收益相关性 |
|---|---|---:|
{correlations}

## 冻结门槛

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
