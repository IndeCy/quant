"""纳指黄金容量失败的分期归因与当前状态审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq_gold_capacity_execution_audit as source
from examples import nasdaq_gold_sp500_hurdle_study as base
from factors.etf_momentum import month_end_signal_dates
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


EXPERIMENT_ID = "nasdaq_gold_60_40_capacity_failure_attribution_audit_v1"
REPORT_PATH = Path(
    "docs/research/"
    "nasdaq-gold-60-40-capacity-failure-attribution-audit-v1.md"
)
CAPITAL = 1_000_000.0
ROLLING_DAYS = 252
PERSISTENCE_MONTHS = 12
PERIODS = {
    "2019": ("20190101", "20191231"),
    "2020_2021": ("20200101", "20211231"),
    "2022": ("20220101", "20221231"),
    "2023_latest": ("20230101", "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指黄金60/40容量失败分期归因 V1",
    category="execution_audit",
    hypothesis=(
        "源容量审计失败是否集中于159941早期低流动性，且当前连续12个月"
        "滚动P90参与率是否已经恢复到100万元1%门槛内"
    ),
    definition={
        "source_capacity_audit": source.EXPERIMENT_ID,
        "source_strategy": base.EXPERIMENT_ID,
        "capital": CAPITAL,
        "periods": PERIODS,
        "rolling": {
            "window_days": ROLLING_DAYS,
            "sample_at": "month_end",
            "persistence_months": PERSISTENCE_MONTHS,
        },
        "frozen_gate": {
            "latest_participation_max": 0.01,
            "trailing_252d_p90_participation_max": 0.01,
            "consecutive_months_passing_min": PERSISTENCE_MONTHS,
        },
        "classification": (
            "current_capacity_recovered_but_historical_bias_when_current_passes"
        ),
        "does_not_override_source_capacity_failure": True,
        "does_not_restate_historical_returns": True,
        "promotion_scope": "failure_attribution_only",
        "methodology_version": "fixed_eras_rolling_252d_v1",
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
        require_source_flagged(paths)
        result, periods, rolling = calculate(paths, normalized)
        complete_attempt(attempt, result, periods, rolling)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    raw = source.load_raw_bars(paths, as_of_date)
    raw = raw.sort_values(["symbol", "trade_date"]).copy()
    raw["participation"] = raw.apply(
        lambda row: (
            CAPITAL
            * source.WEIGHTS[str(row["symbol"])]
            / (float(row["amount"]) * source.AMOUNT_MULTIPLIER)
        ),
        axis=1,
    )
    periods = summarize_periods(raw, as_of_date)
    rolling = build_month_end_rolling(raw)
    nasdaq = rolling[rolling["symbol"].eq(base.NASDAQ)].copy()
    latest_by_symbol = (
        rolling.sort_values("trade_date").groupby("symbol").tail(1)
    )
    latest_pass = bool(
        latest_by_symbol["latest_participation"].le(0.01).all()
    )
    rolling_pass = bool(
        latest_by_symbol["rolling_p90_participation"].le(0.01).all()
    )
    nasdaq_tail = nasdaq.tail(PERSISTENCE_MONTHS)
    persistence_pass = bool(
        len(nasdaq_tail) == PERSISTENCE_MONTHS
        and nasdaq_tail["rolling_p90_participation"].le(0.01).all()
    )
    recovery_date = persistent_recovery_date(
        nasdaq,
        threshold=0.01,
        months=PERSISTENCE_MONTHS,
    )
    checks = {
        "latest_participation_within_1pct": latest_pass,
        "trailing_252d_p90_participation_within_1pct": rolling_pass,
        "nasdaq_twelve_consecutive_months_within_1pct": persistence_pass,
    }
    current_recovered = all(checks.values())
    result = {
        "as_of_date": as_of_date,
        "capital": CAPITAL,
        "periods": periods.to_dict("records"),
        "latest_rolling": latest_by_symbol.to_dict("records"),
        "nasdaq_persistent_recovery_date": recovery_date,
        "gate": {"checks": checks, "passed": current_recovered},
        "classification": (
            "CURRENT_CAPACITY_RECOVERED_BUT_HISTORICAL_BIAS"
            if current_recovered
            else "CURRENT_CAPACITY_NOT_ESTABLISHED"
        ),
        "source_capacity_outcome_unchanged": "RISK_FLAGGED",
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, periods, rolling


def summarize_periods(
    raw: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, (start, end) in PERIODS.items():
        finish = as_of_date if end == "LATEST" else end
        period = raw[
            raw["trade_date"].between(start, finish, inclusive="both")
        ]
        for symbol in source.SYMBOLS:
            values = period.loc[
                period["symbol"].eq(symbol), "participation"
            ]
            rows.append(
                {
                    "period": label,
                    "symbol": symbol,
                    "days": int(len(values)),
                    "median_participation": float(values.median()),
                    "p90_participation": float(values.quantile(0.90)),
                    "maximum_participation": float(values.max()),
                    "share_within_1pct": float(values.le(0.01).mean()),
                }
            )
    return pd.DataFrame(rows)


def build_month_end_rolling(raw: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol in source.SYMBOLS:
        values = (
            raw[raw["symbol"].eq(symbol)]
            .sort_values("trade_date")
            .set_index(pd.to_datetime(
                raw.loc[raw["symbol"].eq(symbol), "trade_date"]
            ))
        )
        participation = values["participation"]
        rolling_p90 = participation.rolling(
            ROLLING_DAYS, min_periods=ROLLING_DAYS
        ).quantile(0.90)
        month_ends = set(month_end_signal_dates(list(participation.index)))
        for date in participation.index:
            if date not in month_ends or pd.isna(rolling_p90.loc[date]):
                continue
            rows.append(
                {
                    "trade_date": date.strftime("%Y%m%d"),
                    "symbol": symbol,
                    "latest_participation": float(participation.loc[date]),
                    "rolling_p90_participation": float(
                        rolling_p90.loc[date]
                    ),
                }
            )
    return pd.DataFrame(rows)


def persistent_recovery_date(
    rolling: pd.DataFrame,
    *,
    threshold: float,
    months: int,
) -> str | None:
    passing = rolling["rolling_p90_participation"].le(threshold).tolist()
    dates = rolling["trade_date"].astype(str).tolist()
    for index in range(months - 1, len(passing)):
        if all(passing[index - months + 1 : index + 1]):
            return dates[index - months + 1]
    return None


def require_source_flagged(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("容量审计依赖尚未成功完成")
    if latest.get("outcome") != "RISK_FLAGGED":
        raise RuntimeError(
            f"容量审计结论不是RISK_FLAGGED: {latest.get('outcome')}"
        )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    periods: pd.DataFrame,
    rolling: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    periods_path = attempt.output_dir / "fixed_periods.csv"
    periods.to_csv(periods_path, index=False)
    rolling_path = attempt.output_dir / "month_end_rolling_252d.csv"
    rolling.to_csv(rolling_path, index=False)
    metrics_path = attempt.output_dir / "attribution_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["classification"]),
        decision_reason=(
            "当前容量连续恢复，但2019至2022历史回测仍有不可忽略的成交偏差"
            if result["gate"]["passed"]
            else "当前连续容量证据仍不足"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "容量失败分期归因"),
            ExperimentArtifact("periods", periods_path, "固定分期容量统计"),
            ExperimentArtifact("rolling", rolling_path, "滚动容量序列"),
            ExperimentArtifact("metrics", metrics_path, "归因指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {item['period']} | {item['symbol']} | {item['days']} | "
        f"{item['median_participation']:.3%} | "
        f"{item['p90_participation']:.3%} | "
        f"{item['share_within_1pct']:.1%} |"
        for item in result["periods"]
    )
    latest = "\n".join(
        f"| {item['symbol']} | {item['trade_date']} | "
        f"{item['latest_participation']:.3%} | "
        f"{item['rolling_p90_participation']:.3%} |"
        for item in result["latest_rolling"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 纳指黄金60/40容量失败分期归因 V1

- 固定本金：{result['capital']:,.0f}元。
- 分类：{result['classification']}。
- 159941 连续容量恢复起点：
  {result['nasdaq_persistent_recovery_date'] or '尚未形成'}。
- 源容量审计仍保持：{result['source_capacity_outcome_unchanged']}。

| 时段 | 标的 | 日数 | 参与率中位 | 参与率P90 | 1%以内占比 |
|---|---|---:|---:|---:|---:|
{periods}

| 标的 | 最新月末 | 当日参与率 | 滚动252日P90 |
|---|---|---:|---:|
{latest}

## 当前容量门槛

{checks}

当前容量恢复不能倒推早期历史回测可成交。源策略2019至2022的M0结果仍须标注
成交容量偏差，本归因审计不覆盖或改写源研究结论。
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
