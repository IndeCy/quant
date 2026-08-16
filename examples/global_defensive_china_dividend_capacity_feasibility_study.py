"""全球防守90%与红利低波10%组合的固定资金容量门禁。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples import global_defensive_equal_study as core
from examples import nasdaq_gold_china_dividend_study as dividend_source
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


EXPERIMENT_ID = "global_defensive_china_dividend_90_10_capacity_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/global-defensive-china-dividend-90-10-capacity-feasibility-v1.md"
)
DIVIDEND = dividend_source.DIVIDEND
WEIGHTS = {
    core.SP500_SYMBOL: 0.30,
    core.GOLD_SYMBOL: 0.30,
    core.BOND_SYMBOL: 0.30,
    DIVIDEND: 0.10,
}
NAMES = {
    core.SP500_SYMBOL: "标普500ETF",
    core.GOLD_SYMBOL: "黄金ETF",
    core.BOND_SYMBOL: "5年国债ETF",
    DIVIDEND: "红利低波ETF",
}
INITIAL_CAPITAL = 1_000_000.0
MAX_PARTICIPATION = 0.01
LOAD_START = "20190118"
STUDY_START = "20200101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球防守90%×红利低波10%容量可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "在100万元与1%成交参与率约束下，红利低波10%硬上限卫星是否具备历史容量"
    ),
    definition={
        "portfolio_preview": {
            "weights": WEIGHTS,
            "capital": INITIAL_CAPITAL,
            "monthly_rebalance": True,
            "return_backtest": False,
        },
        "capacity": {
            "amount_unit": "thousand_cny",
            "initial_order_participation_formula": (
                "capital*weight/(daily_amount*1000)"
            ),
            "median_participation_max": MAX_PARTICIPATION,
            "p90_participation_max": 0.02,
        },
        "gates": {
            "common_days_min": 1800,
            "monthly_signals_min": 75,
            "staleness_days_max": 5,
            "median_participation_max": MAX_PARTICIPATION,
            "p90_participation_max": 0.02,
        },
        "weights_fixed_before_return_loading": True,
        "decision": "capacity_only_no_return_backtest",
        "methodology_version": "fixed_capital_capacity_v1",
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
        data_version=core._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, capacity = calculate(paths, as_of_date)
        complete_attempt(attempt, result, capacity)
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
        list(WEIGHTS),
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    bars = panel.bars.reset_index()
    bars = bars[bars["date"].ge(pd.Timestamp(STUDY_START))].copy()
    rows = []
    for symbol, weight in WEIGHTS.items():
        amount_cny = (
            pd.to_numeric(
                bars.loc[bars["symbol"].eq(symbol), "amount"],
                errors="coerce",
            )
            * 1_000.0
        )
        order_value = INITIAL_CAPITAL * weight
        participation = order_value / amount_cny.replace(0, pd.NA)
        rows.append(
            {
                "symbol": symbol,
                "name": NAMES[symbol],
                "weight": weight,
                "initial_order_value": order_value,
                "median_daily_amount": float(amount_cny.median()),
                "median_participation": float(participation.median()),
                "p90_participation": float(participation.quantile(0.90)),
                "maximum_participation": float(participation.max()),
                "valid_days": int(participation.notna().sum()),
            }
        )
    capacity = pd.DataFrame(rows)
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)
    ).days
    checks = {
        "all_four_assets_present": (
            {str(item["symbol"]) for item in panel.coverage} == set(WEIGHTS)
        ),
        "common_days_at_least_1800": len(panel.calendar) >= 1800,
        "monthly_signals_at_least_75": len(signals) >= 75,
        "fresh_within_five_days": 0 <= staleness <= 5,
        "all_median_participation_within_1pct": bool(
            capacity["median_participation"].le(MAX_PARTICIPATION).all()
        ),
        "all_p90_participation_within_2pct": bool(
            capacity["p90_participation"].le(0.02).all()
        ),
        "no_missing_capacity_days": bool(
            capacity["valid_days"].ge(1700).all()
        ),
    }
    result = {
        "latest_common_date": panel.latest_common_date,
        "common_days": len(panel.calendar),
        "monthly_signals": len(signals),
        "initial_capital": INITIAL_CAPITAL,
        "max_participation": MAX_PARTICIPATION,
        "capacity": capacity.to_dict("records"),
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
    return result, capacity


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    capacity: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    capacity_path = attempt.output_dir / "capacity_cases.csv"
    capacity.to_csv(capacity_path, index=False)
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "100万资金下90/10组合的中位与P90参与率门禁通过"
            if passed
            else "固定资本容量门禁未通过，收益回测前终止"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "容量可行性报告"),
            ExperimentArtifact("capacity", capacity_path, "逐资产容量统计"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {item['symbol']} | {item['name']} | {item['weight']:.0%} | "
        f"{item['initial_order_value']:,.0f} | "
        f"{item['median_daily_amount']:,.0f} | "
        f"{item['median_participation']:.3%} | "
        f"{item['p90_participation']:.3%} |"
        for item in result["capacity"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 全球防守90%×红利低波10%容量可行性 V1

- 固定资金：{result['initial_capital']:,.0f}元；最大参与率：
  {result['max_participation']:.1%}。
- 权重先验固定为标普/黄金/国债各30%，红利低波10%。
- 本阶段不计算组合收益。

| 代码 | 资产 | 权重 | 初始订单 | 日成交额中位 | 参与率中位 | 参与率P90 |
|---|---|---:|---:|---:|---:|---:|
{rows}

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
