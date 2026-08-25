"""纳指黄金60/40与直接场内标普500的同资金容量比较。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples import nasdaq_gold_capacity_execution_audit as capacity
from examples import nasdaq_gold_sp500_hurdle_study as base
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


EXPERIMENT_ID = "nasdaq_gold_60_40_sp500_capacity_comparison_audit_v1"
REPORT_PATH = Path(
    "docs/research/nasdaq-gold-60-40-sp500-capacity-comparison-audit-v1.md"
)
CAPITAL = 1_000_000.0
PORTFOLIOS = {
    "nasdaq_gold_60_40": dict(base.CANDIDATE_WEIGHTS),
    "sp500_direct": {base.SP500: 1.0},
}
PERIODS = {
    "2019": ("20190101", "20191231"),
    "2020_2021": ("20200101", "20211231"),
    "2022": ("20220101", "20221231"),
    "2023_latest": ("20230101", "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指黄金与场内标普同资金容量比较 V1",
    category="execution_audit",
    hypothesis=(
        "在相同100万元一次性建仓假设下，候选和直接标普对照的历史容量偏差"
        "是否为跨境ETF共同问题，以及当前哪一方的约束更强"
    ),
    definition={
        "source_strategy": base.EXPERIMENT_ID,
        "source_capacity_audit": capacity.EXPERIMENT_ID,
        "capital": CAPITAL,
        "portfolios": PORTFOLIOS,
        "binding_participation": (
            "max_over_components(capital*weight/(daily_amount*1000))"
        ),
        "periods": PERIODS,
        "frozen_gate": {
            "latest_binding_participation_max": 0.01,
            "post_2023_p90_binding_participation_max": 0.02,
        },
        "does_not_override_either_source_gate": True,
        "promotion_scope": "relative_execution_capacity_only",
        "methodology_version": "equal_capital_binding_component_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    normalized = min(str(as_of_date).replace("-", ""), base.RELIABLE_AS_OF)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized,
        data_version=base._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_dependencies(paths)
        result, daily, periods = calculate(paths, normalized)
        complete_attempt(attempt, result, daily, periods)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    symbols = list(
        dict.fromkeys(
            symbol
            for weights in PORTFOLIOS.values()
            for symbol in weights
        )
    )
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        symbols,
        start_date="20190101",
        end_date=as_of_date,
    )
    bars = panel.bars.reset_index()
    bars["amount_cny"] = (
        pd.to_numeric(bars["amount"], errors="coerce")
        * capacity.AMOUNT_MULTIPLIER
    )
    daily = build_binding_participation(bars)
    periods = summarize_periods(daily, as_of_date)
    latest = (
        daily.sort_values("trade_date").groupby("portfolio").tail(1)
    )
    post = periods[periods["period"].eq("2023_latest")]
    checks = {
        "both_latest_binding_participation_within_1pct": bool(
            latest["binding_participation"].le(0.01).all()
        ),
        "both_post_2023_p90_binding_participation_within_2pct": bool(
            post["p90_binding_participation"].le(0.02).all()
        ),
    }
    passed = all(checks.values())
    latest_map = latest.set_index("portfolio")[
        "binding_participation"
    ].to_dict()
    result = {
        "as_of_date": as_of_date,
        "latest_common_date": panel.latest_common_date,
        "capital": CAPITAL,
        "latest": latest.to_dict("records"),
        "periods": periods.to_dict("records"),
        "gate": {"checks": checks, "passed": passed},
        "classification": (
            "BOTH_CURRENTLY_EXECUTABLE_CANDIDATE_LESS_CONSTRAINED"
            if passed
            and latest_map["nasdaq_gold_60_40"] < latest_map["sp500_direct"]
            else (
                "BOTH_CURRENTLY_EXECUTABLE"
                if passed
                else "RELATIVE_CAPACITY_RISK"
            )
        ),
        "historical_capacity_bias_common_to_both": bool(
            periods[
                periods["period"].isin(["2019", "2020_2021"])
            ]["p90_binding_participation"].gt(0.01).all()
        ),
        "candidate_2019_more_constrained_than_sp500": bool(
            _period_value(periods, "nasdaq_gold_60_40", "2019")
            > _period_value(periods, "sp500_direct", "2019")
        ),
        "source_gates_overridden": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, daily, periods


def build_binding_participation(bars: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for portfolio, weights in PORTFOLIOS.items():
        subset = bars[bars["symbol"].isin(weights)].copy()
        subset["participation"] = subset.apply(
            lambda row: (
                CAPITAL
                * weights[str(row["symbol"])]
                / float(row["amount_cny"])
            ),
            axis=1,
        )
        for trade_date, group in subset.groupby("date", sort=True):
            if set(group["symbol"]) != set(weights):
                continue
            binding = group.loc[group["participation"].idxmax()]
            rows.append(
                {
                    "trade_date": pd.Timestamp(trade_date).strftime("%Y%m%d"),
                    "portfolio": portfolio,
                    "binding_symbol": str(binding["symbol"]),
                    "binding_participation": float(
                        binding["participation"]
                    ),
                }
            )
    return pd.DataFrame(rows)


def summarize_periods(
    daily: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, (start, end) in PERIODS.items():
        finish = as_of_date if end == "LATEST" else end
        for portfolio in PORTFOLIOS:
            values = daily[
                daily["portfolio"].eq(portfolio)
                & daily["trade_date"].between(start, finish)
            ]["binding_participation"]
            rows.append(
                {
                    "period": label,
                    "portfolio": portfolio,
                    "days": int(len(values)),
                    "median_binding_participation": float(values.median()),
                    "p90_binding_participation": float(
                        values.quantile(0.90)
                    ),
                    "maximum_binding_participation": float(values.max()),
                    "share_within_1pct": float(values.le(0.01).mean()),
                }
            )
    return pd.DataFrame(rows)


def _period_value(
    periods: pd.DataFrame,
    portfolio: str,
    period: str,
) -> float:
    row = periods[
        periods["portfolio"].eq(portfolio)
        & periods["period"].eq(period)
    ].iloc[0]
    return float(row["p90_binding_participation"])


def require_dependencies(paths: RuntimePaths) -> None:
    repository = SystemRepository(paths.system_state_path)
    expected = {
        base.EXPERIMENT_ID: "PASSED_RESEARCH_GATE",
        capacity.EXPERIMENT_ID: "RISK_FLAGGED",
    }
    for experiment_id, expected_outcome in expected.items():
        detail = repository.load_experiment_detail(experiment_id)
        latest = detail.get("latest_run") if detail else None
        if not latest or latest.get("status") != "SUCCESS":
            raise RuntimeError(f"依赖未成功: {experiment_id}")
        if latest.get("outcome") != expected_outcome:
            raise RuntimeError(
                f"依赖结论不符: {experiment_id}={latest.get('outcome')}"
            )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    daily: pd.DataFrame,
    periods: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    daily_path = attempt.output_dir / "daily_binding_participation.csv"
    daily.to_csv(daily_path, index=False)
    periods_path = attempt.output_dir / "fixed_period_comparison.csv"
    periods.to_csv(periods_path, index=False)
    metrics_path = attempt.output_dir / "capacity_comparison_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "PASSED_EXECUTION_AUDIT"
            if result["gate"]["passed"]
            else "RISK_FLAGGED"
        ),
        decision_reason=(
            "两者当前容量均通过；候选当前约束低于直接标普，但早期偏差更严重"
            if result["gate"]["passed"]
            else "候选或直接标普的当前容量未通过冻结门槛"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "同资金容量比较"),
            ExperimentArtifact("daily", daily_path, "逐日约束参与率"),
            ExperimentArtifact("periods", periods_path, "固定分期比较"),
            ExperimentArtifact("metrics", metrics_path, "容量比较指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {item['period']} | {item['portfolio']} | {item['days']} | "
        f"{item['median_binding_participation']:.3%} | "
        f"{item['p90_binding_participation']:.3%} | "
        f"{item['share_within_1pct']:.1%} |"
        for item in result["periods"]
    )
    latest = "\n".join(
        f"| {item['portfolio']} | {item['trade_date']} | "
        f"{item['binding_symbol']} | "
        f"{item['binding_participation']:.3%} |"
        for item in result["latest"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 纳指黄金60/40与场内标普同资金容量比较 V1

- 固定本金：{result['capital']:,.0f}元；一次性完整建仓。
- 分类：{result['classification']}。
- 早期容量偏差是否两者共有：
  {result['historical_capacity_bias_common_to_both']}。
- 候选2019年是否比直接标普更受约束：
  {result['candidate_2019_more_constrained_than_sp500']}。

| 时段 | 组合 | 日数 | 约束参与率中位 | P90 | 1%以内占比 |
|---|---|---:|---:|---:|---:|
{periods}

| 组合 | 最新日 | 约束标的 | 约束参与率 |
|---|---|---|---:|
{latest}

## 冻结门槛

{checks}

比较只衡量成交额容量，不代表场内溢价、IOPV、开盘冲击或跟踪误差相同，
也不覆盖任一源研究门槛。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_study(
                get_runtime_paths(),
                args.as_of_date,
                force=args.force,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
