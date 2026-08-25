"""QDII最新两个月折溢价分布与归一化冲击审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import qdii_current_nav_monitoring_audit as source
from examples import nasdaq_gold_sp500_hurdle_study as base
from runtime.config import get_config_value
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


EXPERIMENT_ID = "qdii_current_premium_window_audit_v2"
REPORT_PATH = Path("docs/research/qdii-current-premium-window-audit-v2.md")
NASDAQ_WEIGHT = 0.60
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="QDII当前折溢价窗口归因 V2",
    category="execution_audit",
    hypothesis=(
        "159941当前11%溢价是否在近两个月持续偏高，以及按60%组合权重"
        "完全归一化时的净值冲击是否越过历史冻结的-6%底线"
    ),
    definition={
        "source_monitoring_audit": source.EXPERIMENT_ID,
        "window_start": source.LOOKBACK_START,
        "external_read": {
            "provider": "Tushare Pro fund_nav",
            "writes_production_database": False,
        },
        "premium_formula": "same_date_raw_close/unit_nav-1",
        "normalization_shock": (
            "nasdaq_weight*(-latest_premium/(1+latest_premium))"
        ),
        "frozen_gate": {
            "matched_observations_each_min": 30,
            "nav_staleness_days_max": 7,
            "nasdaq_latest_premium_max": 0.10,
            "weighted_normalization_shock_floor": -0.06,
            "unexplained_absolute_premium_max": 0.50,
        },
        "does_not_replace_realtime_iopv": True,
        "does_not_override_source_gate": True,
        "promotion_scope": "current_premium_attribution_only",
        "methodology_version": "same_date_two_month_window_v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client: Any | None = None,
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
        resolved = client or source.TushareNavClient(
            get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        )
        result, daily = calculate(paths, normalized, resolved)
        complete_attempt(attempt, result, daily)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
    client: Any,
) -> tuple[dict[str, Any], pd.DataFrame]:
    nav = source.load_current_nav(client, as_of_date)
    prices = source.load_raw_closes(paths, nav, as_of_date)
    daily = build_matched_premiums(nav, prices)
    summaries = summarize_window(daily, as_of_date)
    nasdaq = summaries[base.NASDAQ]
    normalization_shock = (
        NASDAQ_WEIGHT
        * (-nasdaq["latest_premium"] / (1.0 + nasdaq["latest_premium"]))
    )
    checks = {
        "each_symbol_has_at_least_30_matches": all(
            item["matched_rows"] >= 30 for item in summaries.values()
        ),
        "all_nav_staleness_within_seven_days": all(
            item["nav_staleness_days"] <= 7 for item in summaries.values()
        ),
        "nasdaq_latest_premium_within_10pct": (
            nasdaq["latest_premium"] <= 0.10
        ),
        "weighted_normalization_shock_within_6pct": (
            normalization_shock >= -0.06
        ),
        "no_absolute_premium_above_50pct": all(
            item["maximum_absolute_premium"] <= 0.50
            for item in summaries.values()
        ),
    }
    if not checks["weighted_normalization_shock_within_6pct"]:
        classification = "NORMALIZATION_SHOCK_RISK"
    elif not checks["nasdaq_latest_premium_within_10pct"]:
        classification = "PREMIUM_ELEVATED_NEAR_NORMALIZATION_LIMIT"
    elif all(checks.values()):
        classification = "CURRENT_PREMIUM_WITHIN_LIMIT"
    else:
        classification = "CURRENT_PREMIUM_DATA_RISK"
    result = {
        "as_of_date": as_of_date,
        "window_start": source.LOOKBACK_START,
        "summaries": summaries,
        "nasdaq_weight": NASDAQ_WEIGHT,
        "weighted_full_normalization_shock": float(normalization_shock),
        "gate": {"checks": checks, "passed": all(checks.values())},
        "classification": classification,
        "realtime_iopv_available": False,
        "source_gate_overridden": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    return result, daily


def build_matched_premiums(
    nav: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    matched = nav[["symbol", "end_date", "unit_nav"]].merge(
        prices[["symbol", "trade_date", "close"]],
        left_on=["symbol", "end_date"],
        right_on=["symbol", "trade_date"],
        how="inner",
        validate="one_to_one",
    )
    matched["premium"] = matched["close"] / matched["unit_nav"] - 1.0
    return matched.sort_values(["symbol", "end_date"]).reset_index(drop=True)


def summarize_window(
    daily: pd.DataFrame,
    as_of_date: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for symbol in source.SYMBOLS:
        values = daily[daily["symbol"].eq(symbol)].sort_values("end_date")
        if values.empty:
            continue
        premium = values["premium"]
        latest_date = str(values["end_date"].iloc[-1])
        result[symbol] = {
            "matched_rows": int(len(values)),
            "first_nav_date": str(values["end_date"].iloc[0]),
            "latest_nav_date": latest_date,
            "nav_staleness_days": int(
                (pd.Timestamp(as_of_date) - pd.Timestamp(latest_date)).days
            ),
            "first_premium": float(premium.iloc[0]),
            "latest_premium": float(premium.iloc[-1]),
            "median_premium": float(premium.median()),
            "premium_p05": float(premium.quantile(0.05)),
            "premium_p95": float(premium.quantile(0.95)),
            "maximum_absolute_premium": float(premium.abs().max()),
            "share_above_5pct": float(premium.gt(0.05).mean()),
            "share_above_10pct": float(premium.gt(0.10).mean()),
        }
    return result


def require_source_flagged(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("当前净值监控审计依赖尚未成功")
    if latest.get("outcome") != "RISK_FLAGGED":
        raise RuntimeError(
            f"当前净值监控审计未标记风险: {latest.get('outcome')}"
        )


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    daily: pd.DataFrame,
) -> None:
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    daily_path = attempt.output_dir / "matched_daily_premiums.csv"
    daily.to_csv(daily_path, index=False)
    metrics_path = attempt.output_dir / "premium_window_metrics.json"
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
            "当前两个月QDII折溢价与归一化冲击均在冻结范围内"
            if result["gate"]["passed"]
            else "159941当前溢价或归一化冲击越过冻结范围"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "当前折溢价窗口报告"),
            ExperimentArtifact("daily", daily_path, "同日折溢价序列"),
            ExperimentArtifact("metrics", metrics_path, "窗口审计指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {symbol} | {item['matched_rows']} | "
        f"{item['median_premium']:.2%} | {item['premium_p95']:.2%} | "
        f"{item['latest_premium']:.2%} | {item['share_above_10pct']:.1%} |"
        for symbol, item in result["summaries"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# QDII当前折溢价窗口归因 V2

- 窗口：{result['window_start']} 至 {result['as_of_date']}。
- 分类：{result['classification']}。
- 159941按组合60%权重完全归一化冲击：
  {result['weighted_full_normalization_shock']:.2%}。
- 仅为日频同日净值监控，不能替代盘中IOPV。

| 代码 | 匹配日 | 溢价中位 | P95 | 最新 | 超10%占比 |
|---|---:|---:|---:|---:|---:|
{rows}

## 冻结门槛

{checks}

当前风险标记不改写历史回测；它表示按最新场内价格追入，可能承担额外的
溢价回归损失。
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
