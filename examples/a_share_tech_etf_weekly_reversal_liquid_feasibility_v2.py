"""剔除未达流动性门槛资产后的科技ETF反转数据门禁 V2。"""

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
from examples import a_share_tech_etf_weekly_reversal_feasibility_study as v1
from factors.etf_relative_strength import weekly_signal_dates
from factors.etf_short_term_reversal import calculate_weekly_reversal_states
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


EXPERIMENT_ID = "a_share_tech_etf_weekly_reversal_liquid_feasibility_v2"
REPORT_PATH = Path(
    "docs/research/a-share-tech-etf-weekly-reversal-liquid-feasibility-v2.md"
)
EXCLUDED = "512930.SH"
LIQUID_SYMBOLS = [
    symbol for symbol in tech.TECH_SYMBOLS if symbol != EXCLUDED
]
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="A股科技ETF周频5日反转流动性修订 V2",
    category="data_feasibility",
    hypothesis="仅剔除V1中未达成交额门槛的人工智能ETF后，固定四只池能否通过数据门禁",
    definition={
        "source_feasibility": v1.EXPERIMENT_ID,
        "universe": {
            "included": LIQUID_SYMBOLS,
            "excluded": {
                EXCLUDED: "V1 median_amount_below_frozen_30000_threshold",
            },
            "return_metrics_used_for_revision": False,
        },
        "signal_preview": v1.RESEARCH_SPEC.definition["signal_preview"],
        "gates": v1.RESEARCH_SPEC.definition["gates"],
        "further_universe_revision": "forbidden",
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "liquidity_adjustment_v2",
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
        require_v1_liquidity_only_failure(paths)
        result, states = calculate(paths, as_of_date)
        complete_attempt(attempt, result, states)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def require_v1_liquidity_only_failure(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        v1.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("V1数据门禁尚未成功完成")
    metrics = latest.get("metrics") or {}
    checks = metrics.get("checks") or {}
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed != ["all_median_amount_at_least_30000"]:
        raise RuntimeError(f"V1并非仅流动性失败: {failed}")
    if latest.get("outcome") != "REJECTED":
        raise RuntimeError("V1必须保持回测前拒绝")


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        LIQUID_SYMBOLS,
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
        LIQUID_SYMBOLS,
        lookback_days=v1.LOOKBACK_DAYS,
    )
    result = v1.evaluate(
        panel,
        states,
        signals,
        as_of_date,
        symbols=LIQUID_SYMBOLS,
    )
    report = paths.root / REPORT_PATH
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report)
    result["reused"] = False
    return result, states


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
            "四只流动性合格科技ETF的周频反转数据门禁通过"
            if passed
            else "流动性修订池仍未通过，终止该研究方向"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "流动性修订门禁报告"),
            ExperimentArtifact("state_preview", states_path, "历史信号状态"),
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
    return f"""# A股科技ETF周频5日反转流动性修订 V2

- V1未读取持有期收益，且唯一失败为人工智能ETF成交额中位数不足。
- V2仅剔除512930.SH；其余四只、5日窗口、周频和冻结门槛不变。
- 共同截止：{result['latest_common_date']}；完整周：
  {result['complete_weeks']}/{result['expected_weeks']}。

| 代码 | 名称 | 日成交额中位数（源字段单位） |
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
