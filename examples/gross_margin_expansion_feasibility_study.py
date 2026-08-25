"""连续年报毛利率改善因子的点时覆盖可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.gross_margin_change import (
    GROSS_MARGIN_CHANGE_TABLE,
    GrossMarginFinancialPaths,
    attach_gross_margin_financial_database,
    create_gross_margin_signal_date_table,
    materialize_gross_margin_change_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import load_month_end_signal_dates, materialize_market_features
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "gross_margin_expansion_data_feasibility_v1"
REPORT_PATH = Path("docs/research/gross-margin-expansion-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
MIN_CANDIDATES = 500
MIN_MONTH_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="毛利率改善数据可行性 V1",
    category="data_feasibility",
    hypothesis="连续两份已披露年报的毛利率变化能否稳定覆盖A股月频截面",
    definition={
        "factor": {
            "formula": "(revenue-oper_cost)/revenue-current_minus_prior_year",
            "annual_reports_only": True,
            "requires_consecutive_years": True,
        },
        "visibility": {
            "field": "f_ann_date",
            "rule": "latest_revision_lte_signal_date",
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "month_share": MIN_MONTH_SHARE,
            "locked_period_same_gate": True,
            "visibility_violations": 0,
        },
        "decision": "feasibility_only_no_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记研究身份，再读取利润表与全A行情。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """统计标准可投股票池中的连续年报覆盖。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_gross_margin_signal_date_table(connection, signal_dates)
        attach_gross_margin_financial_database(
            connection,
            GrossMarginFinancialPaths(paths.income_statement_path),
        )
        materialize_gross_margin_change_asof(connection)
        monthly = load_monthly_coverage(connection)
        distribution = load_latest_distribution(connection)
        visibility_violations = int(
            connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {GROSS_MARGIN_CHANGE_TABLE}
                WHERE publish_date > signal_date
                   OR prior_publish_date > signal_date
                """
            ).fetchone()[0]
        )
    finally:
        connection.close()
    result = evaluate_feasibility(
        monthly,
        distribution,
        visibility_violations,
        latest_date,
    )
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_monthly_coverage(connection: Any) -> pd.DataFrame:
    """按统一可投股票池统计可用毛利率变化样本数。"""
    return connection.execute(
        f"""
        SELECT
            f.trade_date AS signal_date,
            COUNT(g.symbol) AS candidate_count
        FROM features f
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN {GROSS_MARGIN_CHANGE_TABLE} g
          ON f.trade_date = g.signal_date AND f.symbol = g.symbol
        WHERE f.trade_date IN (
            SELECT signal_date FROM gross_margin_signal_dates
        )
          AND f.st_name IS NULL
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
        GROUP BY f.trade_date
        ORDER BY f.trade_date
        """
    ).fetchdf()


def load_latest_distribution(connection: Any) -> dict[str, float]:
    """记录最新截面变化幅度，识别量纲和异常值。"""
    row = connection.execute(
        f"""
        SELECT
            QUANTILE_CONT(gross_margin_change, 0.01),
            QUANTILE_CONT(gross_margin_change, 0.50),
            QUANTILE_CONT(gross_margin_change, 0.99)
        FROM {GROSS_MARGIN_CHANGE_TABLE}
        WHERE signal_date = (
            SELECT MAX(signal_date) FROM {GROSS_MARGIN_CHANGE_TABLE}
        )
        """
    ).fetchone()
    return {"p01": float(row[0]), "median": float(row[1]), "p99": float(row[2])}


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    visibility_violations: int,
    latest_date: str,
) -> dict[str, Any]:
    """使用冻结的全样本与锁定期覆盖门槛。"""
    if monthly.empty:
        raise ValueError("毛利率改善覆盖审计没有月末数据")
    data = monthly.copy()
    full_share = float(data["candidate_count"].ge(MIN_CANDIDATES).mean())
    locked = data[data["signal_date"].astype(str).ge(LOCKED_START)]
    locked_share = float(
        locked["candidate_count"].ge(MIN_CANDIDATES).mean()
        if not locked.empty
        else 0.0
    )
    checks = {
        "full_candidate_month_share": full_share >= MIN_MONTH_SHARE,
        "locked_candidate_month_share": locked_share >= MIN_MONTH_SHARE,
        "zero_visibility_violations": visibility_violations == 0,
        "finite_latest_distribution": all(
            pd.notna(value) for value in distribution.values()
        ),
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(data)),
        "candidate_count_min": int(data["candidate_count"].min()),
        "candidate_count_median": float(data["candidate_count"].median()),
        "candidate_count_latest": int(data["candidate_count"].iloc[-1]),
        "full_candidate_month_share": full_share,
        "locked_candidate_month_share": locked_share,
        "visibility_violations": visibility_violations,
        "latest_distribution": distribution,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档覆盖明细，未通过时终止于回测前。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "连续年报毛利率变化覆盖稳定，可进入固定定义回测"
            if passed
            else "连续年报毛利率变化覆盖不足，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "毛利率改善可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成仅讨论数据可行性的报告。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    distribution = result["latest_distribution"]
    return f"""# 毛利率改善数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面：
  {result['signal_months']} 个。
- 候选数最少/中位/最新：
  {result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} /
  {result['candidate_count_latest']}。
- 全样本/2022年后达标月份：
  {result['full_candidate_month_share']:.2%} /
  {result['locked_candidate_month_share']:.2%}。
- 公告日越界记录：{result['visibility_violations']}。
- 最新变化幅度 P1/中位/P99：
  {distribution['p01']:.4f} /
  {distribution['median']:.4f} /
  {distribution['p99']:.4f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定利润表和行情快照版本。"""
    parts: list[str] = []
    for label, path in [
        ("income", paths.income_statement_path),
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
