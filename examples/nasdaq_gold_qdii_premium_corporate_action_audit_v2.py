"""剔除公司行动口径切换日后的QDII折溢价审计 V2。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import nasdaq_gold_qdii_premium_audit as v1
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


EXPERIMENT_ID = "nasdaq_gold_60_40_qdii_premium_corporate_action_audit_v2"
REPORT_PATH = Path(
    "docs/research/nasdaq-gold-60-40-qdii-premium-corporate-action-audit-v2.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指黄金QDII公司行动对齐折溢价审计 V2",
    category="execution_audit",
    hypothesis=(
        "V1极端溢价是否仅由复权因子切换日前后价格与NAV口径错位造成，"
        "在固定排除这些日期后风险结论是否保持"
    ),
    definition={
        "source_audit": v1.EXPERIMENT_ID,
        "cleaning_rule": (
            "exclude_rows_where_adj_factor_differs_from_previous_or_next_row"
        ),
        "rule_uses_returns": False,
        "raw_database_mutation": False,
        "premium_formula": v1.RESEARCH_SPEC.definition["premium_formula"],
        "frozen_gate": {
            **v1.RESEARCH_SPEC.definition["frozen_gate"],
            "unexplained_absolute_premium_above_50pct_rows": 0,
            "excluded_share_max": 0.01,
        },
        "does_not_override_source_gate": True,
        "promotion_scope": "execution_risk_audit_only",
        "methodology_version": "qdii_corporate_action_alignment_v2",
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
        data_version=v1.data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_v1_completed(paths)
        result, raw, cleaned = calculate(paths, as_of_date)
        complete_attempt(attempt, result, raw, cleaned)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    raw = load_with_adjustment(paths, as_of_date)
    cleaned_parts: list[pd.DataFrame] = []
    exclusions: dict[str, dict[str, Any]] = {}
    for symbol, group in raw.groupby("symbol", sort=True):
        values = group.sort_values("trade_date").copy()
        factor = pd.to_numeric(values["adj_factor"], errors="coerce")
        transition = factor.ne(factor.shift()) | factor.ne(factor.shift(-1))
        transition.iloc[0] = False
        transition.iloc[-1] = False
        excluded = values.loc[transition].copy()
        kept = values.loc[~transition].copy()
        cleaned_parts.append(kept)
        exclusions[str(symbol)] = {
            "raw_rows": int(len(values)),
            "excluded_rows": int(len(excluded)),
            "excluded_share": float(len(excluded) / len(values)),
            "excluded_dates": excluded["trade_date"].astype(str).tolist(),
        }
    cleaned = pd.concat(cleaned_parts, ignore_index=True)
    summaries = {
        symbol: v1.summarize_premium(
            group.sort_values("trade_date").copy(),
            as_of_date,
        )
        for symbol, group in cleaned.groupby("symbol", sort=True)
    }
    unexplained = {
        symbol: count_unexplained_extremes(group)
        for symbol, group in cleaned.groupby("symbol", sort=True)
    }
    nasdaq = summaries[v1.base.NASDAQ]
    weighted_full = (
        v1.NASDAQ_WEIGHT * nasdaq["annualized_log_premium_contribution"]
    )
    rolling_tail = v1.NASDAQ_WEIGHT * max(
        abs(nasdaq["rolling_252_annual_contribution_p05"]),
        abs(nasdaq["rolling_252_annual_contribution_p95"]),
    )
    latest = nasdaq["latest_premium"]
    shock = v1.NASDAQ_WEIGHT * (-latest / (1.0 + latest))
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
        "last_known_normalization_shock_within_6pct": shock >= -0.06,
        "zero_unexplained_absolute_premium_above_50pct": (
            sum(unexplained.values()) == 0
        ),
        "all_excluded_shares_within_1pct": all(
            item["excluded_share"] <= 0.01
            for item in exclusions.values()
        ),
    }
    result = {
        "as_of_date": as_of_date,
        "summaries": summaries,
        "exclusions": exclusions,
        "unexplained_extreme_rows": unexplained,
        "strategy_risk": {
            "weighted_full_annual_premium_contribution": weighted_full,
            "weighted_rolling_annual_contribution_abs_tail": rolling_tail,
            "last_known_normalization_shock": shock,
            "last_known_nav_date": nasdaq["latest_nav_date"],
            "current_premium_after_last_nav": "UNKNOWN",
        },
        "gate": {"passed": all(checks.values()), "checks": checks},
        "source_gate_overridden": False,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, raw, cleaned


def load_with_adjustment(
    paths: RuntimePaths,
    as_of_date: str,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in v1.QDII_SYMBOLS)
    with duckdb.connect(
        str(paths.fund_daily_history_path),
        read_only=True,
    ) as connection:
        return connection.execute(
            f"""
            SELECT
                trade_date,
                ts_code AS symbol,
                close,
                nav,
                adj_factor
            FROM etf_lof_reits_daily_adj
            WHERE ts_code IN ({placeholders})
              AND trade_date <= ?
            ORDER BY ts_code, trade_date
            """,
            [*v1.QDII_SYMBOLS, as_of_date],
        ).fetchdf()


def count_unexplained_extremes(frame: pd.DataFrame) -> int:
    valid = frame.dropna(subset=["close", "nav"]).copy()
    premium = (
        pd.to_numeric(valid["close"], errors="coerce")
        / pd.to_numeric(valid["nav"], errors="coerce")
        - 1.0
    )
    return int(premium.abs().gt(0.50).sum())


def require_v1_completed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        v1.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("QDII折溢价V1审计尚未成功完成")
    if latest.get("outcome") not in {
        "PASSED_EXECUTION_AUDIT",
        "RISK_FLAGGED",
    }:
        raise RuntimeError("QDII折溢价V1审计结论不可识别")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    raw: pd.DataFrame,
    cleaned: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    metrics_path = attempt.output_dir / "premium_metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raw_path = attempt.output_dir / "raw_close_nav_adjustment.csv"
    raw.to_csv(raw_path, index=False)
    cleaned_path = attempt.output_dir / "cleaned_close_nav_adjustment.csv"
    cleaned.to_csv(cleaned_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_EXECUTION_AUDIT" if passed else "RISK_FLAGGED",
        decision_reason=(
            "公司行动对齐后QDII折溢价风险仍在冻结范围内"
            if passed
            else "公司行动对齐后仍有折溢价风险越界"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "公司行动对齐审计报告"),
            ExperimentArtifact("metrics", metrics_path, "审计指标"),
            ExperimentArtifact("raw", raw_path, "原始价净值复权因子"),
            ExperimentArtifact("cleaned", cleaned_path, "固定规则清洗结果"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {symbol} | {v1.QDII_SYMBOLS[symbol]} | "
        f"{item['excluded_rows']} | {', '.join(item['excluded_dates']) or '-'} | "
        f"{result['summaries'][symbol]['maximum_premium']:.2%} | "
        f"{result['unexplained_extreme_rows'][symbol]} |"
        for symbol, item in result["exclusions"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    risk = result["strategy_risk"]
    return f"""# 纳指黄金QDII公司行动对齐折溢价审计 V2

- 固定清洗：仅排除复权因子切换日前后各一条记录；不按收益或溢价大小删点。
- 原始数据库未修改，源策略研究门槛不覆盖。

| 代码 | 资产 | 排除行数 | 排除日期 | 清洗后最大溢价 | 未解释>|50%|行 |
|---|---|---:|---|---:|---:|
{rows}

## 对60/40组合的清洗后影响

- 全期年化溢价变化贡献：{risk['weighted_full_annual_premium_contribution']:.2%}
- 252日滚动年化贡献绝对尾部：
  {risk['weighted_rolling_annual_contribution_abs_tail']:.2%}
- 最后已知溢价归零冲击：{risk['last_known_normalization_shock']:.2%}
- NAV最后日期：{risk['last_known_nav_date']}；之后实时溢价未知。

## 冻结门槛

{checks}

结论：{'公司行动错位已被固定规则解释，历史折溢价风险仍在冻结范围内' if result['gate']['passed'] else '清洗后仍有折溢价风险越界，不得进入实盘'}。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default="20260728")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
