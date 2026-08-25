"""纳指黄金60/40中跨境ETF场内折溢价的可实现性审计。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


EXPERIMENT_ID = "nasdaq_gold_60_40_qdii_premium_audit_v1"
REPORT_PATH = Path("docs/research/nasdaq-gold-60-40-qdii-premium-audit-v1.md")
QDII_SYMBOLS = {
    base.NASDAQ: "纳斯达克100ETF",
    base.SP500: "标普500ETF对照",
}
NASDAQ_WEIGHT = 0.60
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指黄金60/40跨境ETF折溢价审计 V1",
    category="execution_audit",
    hypothesis=(
        "场内真实价格已包含QDII折溢价，但通过门槛的收益是否过度依赖溢价扩张，"
        "以及当前可观测溢价回归会造成多大组合冲击"
    ),
    definition={
        "source_strategy": base.EXPERIMENT_ID,
        "audited_symbols": QDII_SYMBOLS,
        "premium_formula": "raw_close/unit_nav-1",
        "decomposition": {
            "market_log_return_minus_nav_log_return": (
                "log(1+market_return)-log(1+nav_return)"
            ),
            "rolling_window_days": 252,
            "nasdaq_portfolio_weight": NASDAQ_WEIGHT,
            "counterfactual_is_not_tradable": True,
        },
        "frozen_gate": {
            "nav_coverage_min": 0.95,
            "nav_staleness_days_max": 60,
            "median_absolute_premium_max": 0.03,
            "month_end_premium_above_5pct_share_max": 0.20,
            "weighted_full_annual_premium_contribution_abs_max": 0.01,
            "weighted_rolling_annual_contribution_abs_p95_max": 0.05,
            "last_known_normalization_shock_floor": -0.06,
        },
        "does_not_override_source_gate": True,
        "promotion_scope": "execution_risk_audit_only",
        "methodology_version": "qdii_nav_price_decomposition_v1",
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
        data_version=data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_source_passed(paths)
        result, daily = calculate(paths, as_of_date)
        complete_attempt(attempt, result, daily)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    frame = load_nav_prices(paths, as_of_date)
    summaries = {
        symbol: summarize_premium(
            group.sort_values("trade_date").copy(),
            as_of_date,
        )
        for symbol, group in frame.groupby("symbol", sort=True)
    }
    nasdaq = summaries[base.NASDAQ]
    weighted_full = (
        NASDAQ_WEIGHT * nasdaq["annualized_log_premium_contribution"]
    )
    rolling_tail = NASDAQ_WEIGHT * max(
        abs(nasdaq["rolling_252_annual_contribution_p05"]),
        abs(nasdaq["rolling_252_annual_contribution_p95"]),
    )
    latest_premium = nasdaq["latest_premium"]
    normalization_shock = (
        NASDAQ_WEIGHT * (-latest_premium / (1.0 + latest_premium))
    )
    checks = {
        "all_nav_coverage_at_least_95pct": all(
            item["nav_coverage"] >= 0.95 for item in summaries.values()
        ),
        "all_nav_staleness_within_60_days": all(
            item["nav_staleness_days"] <= 60 for item in summaries.values()
        ),
        "all_median_absolute_premium_within_3pct": all(
            item["median_absolute_premium"] <= 0.03
            for item in summaries.values()
        ),
        "nasdaq_month_end_above_5pct_share_within_20pct": (
            nasdaq["month_end_premium_above_5pct_share"] <= 0.20
        ),
        "weighted_full_annual_premium_contribution_within_1pct": (
            abs(weighted_full) <= 0.01
        ),
        "weighted_rolling_annual_contribution_tail_within_5pct": (
            rolling_tail <= 0.05
        ),
        "last_known_normalization_shock_within_6pct": (
            normalization_shock >= -0.06
        ),
    }
    result = {
        "as_of_date": as_of_date,
        "summaries": summaries,
        "strategy_risk": {
            "nasdaq_weight": NASDAQ_WEIGHT,
            "weighted_full_annual_premium_contribution": weighted_full,
            "weighted_rolling_annual_contribution_abs_tail": rolling_tail,
            "last_known_normalization_shock": normalization_shock,
            "last_known_nav_date": nasdaq["latest_nav_date"],
            "current_premium_after_last_nav": "UNKNOWN",
        },
        "gate": {
            "passed": all(checks.values()),
            "checks": checks,
        },
        "source_gate_overridden": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, frame


def load_nav_prices(paths: RuntimePaths, as_of_date: str) -> pd.DataFrame:
    """只读历史基线中的原始场内收盘与单位净值。"""
    placeholders = ",".join("?" for _ in QDII_SYMBOLS)
    with duckdb.connect(
        str(paths.fund_daily_history_path),
        read_only=True,
    ) as connection:
        frame = connection.execute(
            f"""
            SELECT
                trade_date,
                ts_code AS symbol,
                close,
                nav
            FROM etf_lof_reits_daily_adj
            WHERE ts_code IN ({placeholders})
              AND trade_date <= ?
            ORDER BY ts_code, trade_date
            """,
            [*QDII_SYMBOLS, as_of_date],
        ).fetchdf()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["nav"] = pd.to_numeric(frame["nav"], errors="coerce")
    return frame


def summarize_premium(frame: pd.DataFrame, as_of_date: str) -> dict[str, Any]:
    """汇总覆盖、月末买入暴露和溢价变化对收益的贡献。"""
    total_rows = len(frame)
    valid = frame.dropna(subset=["close", "nav"]).copy()
    valid = valid[valid["close"].gt(0) & valid["nav"].gt(0)]
    if len(valid) < 500:
        raise ValueError("QDII净值有效样本不足500日")
    valid["date"] = pd.to_datetime(valid["trade_date"], format="%Y%m%d")
    valid["premium"] = valid["close"] / valid["nav"] - 1.0
    valid["market_return"] = valid["close"].pct_change(fill_method=None)
    valid["nav_return"] = valid["nav"].pct_change(fill_method=None)
    valid["log_premium_change"] = (
        np.log1p(valid["market_return"])
        - np.log1p(valid["nav_return"])
    )
    contribution = valid["log_premium_change"].dropna()
    annualized = float(contribution.mean() * 252)
    rolling = contribution.rolling(252, min_periods=252).sum()
    month_end = valid.loc[
        valid.groupby(valid["date"].dt.to_period("M"))["date"].idxmax()
    ]
    latest_date = str(valid["trade_date"].iloc[-1])
    staleness = (
        pd.Timestamp(as_of_date) - pd.Timestamp(latest_date)
    ).days
    return {
        "total_price_rows": int(total_rows),
        "valid_nav_rows": int(len(valid)),
        "nav_coverage": float(len(valid) / total_rows) if total_rows else 0.0,
        "first_nav_date": str(valid["trade_date"].iloc[0]),
        "latest_nav_date": latest_date,
        "nav_staleness_days": int(staleness),
        "median_premium": float(valid["premium"].median()),
        "median_absolute_premium": float(valid["premium"].abs().median()),
        "premium_p05": float(valid["premium"].quantile(0.05)),
        "premium_p95": float(valid["premium"].quantile(0.95)),
        "maximum_premium": float(valid["premium"].max()),
        "latest_premium": float(valid["premium"].iloc[-1]),
        "month_end_observations": int(len(month_end)),
        "month_end_premium_above_5pct_share": float(
            month_end["premium"].gt(0.05).mean()
        ),
        "annualized_log_premium_contribution": annualized,
        "rolling_252_windows": int(rolling.notna().sum()),
        "rolling_252_annual_contribution_p05": float(rolling.quantile(0.05)),
        "rolling_252_annual_contribution_median": float(rolling.median()),
        "rolling_252_annual_contribution_p95": float(rolling.quantile(0.95)),
        "premium_identity_error_p99": float(
            (
                contribution
                - (
                    np.log1p(valid["premium"])
                    .diff()
                    .dropna()
                    .reindex(contribution.index)
                )
            )
            .abs()
            .quantile(0.99)
        ),
    }


def require_source_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        base.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("纳指黄金V3依赖尚未成功完成")
    if latest.get("outcome") != "PASSED_RESEARCH_GATE":
        raise RuntimeError("纳指黄金V3依赖未通过研究门槛")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    daily: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    metrics_path = attempt.output_dir / "premium_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    daily_path = attempt.output_dir / "raw_close_nav.csv"
    daily.to_csv(daily_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_EXECUTION_AUDIT" if passed else "RISK_FLAGGED",
        decision_reason=(
            "QDII折溢价历史贡献与回归冲击均在冻结范围内"
            if passed
            else "QDII折溢价风险超出冻结范围，源策略门槛不覆盖且需额外控制"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "折溢价审计报告"),
            ExperimentArtifact("metrics", metrics_path, "审计指标"),
            ExperimentArtifact("raw_close_nav", daily_path, "场内价与单位净值"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {symbol} | {QDII_SYMBOLS[symbol]} | {item['nav_coverage']:.2%} | "
        f"{item['latest_nav_date']} | {item['median_premium']:.2%} | "
        f"{item['premium_p95']:.2%} | {item['maximum_premium']:.2%} | "
        f"{item['latest_premium']:.2%} |"
        for symbol, item in result["summaries"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    risk = result["strategy_risk"]
    return f"""# 纳指黄金60/40跨境ETF折溢价审计 V1

- 场内回测价格本身已包含折溢价，本审计不重算或覆盖源策略门槛。
- 溢价定义：原始收盘价/单位净值-1；净值反事实不可直接成交。
- 审计截止：{result['as_of_date']}。

| 代码 | 资产 | NAV覆盖 | 最后NAV日 | 溢价中位 | 溢价P95 | 最大溢价 | 最后已知溢价 |
|---|---|---:|---|---:|---:|---:|---:|
{rows}

## 对60/40组合的影响

- 全期年化溢价变化贡献（60%权重近似）：
  {risk['weighted_full_annual_premium_contribution']:.2%}
- 252日滚动年化贡献绝对尾部（60%权重近似）：
  {risk['weighted_rolling_annual_contribution_abs_tail']:.2%}
- 最后已知溢价瞬间归零的组合冲击：
  {risk['last_known_normalization_shock']:.2%}
- 最后净值日期：{risk['last_known_nav_date']}；此后当前溢价为
  `{risk['current_premium_after_last_nav']}`，不能用旧NAV外推。

## 冻结门槛

{checks}

结论：{'折溢价风险在冻结范围内，但仍需实盘下单前检查实时IOPV/NAV' if result['gate']['passed'] else '折溢价风险越界；保持研究策略，不得据此直接进入实盘'}。
"""


def data_version(paths: RuntimePaths) -> str:
    stat = paths.fund_daily_history_path.stat()
    return f"fund_history:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260728")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
