"""Piotroski F-Score 在本地 A 股财务数据中的点时覆盖审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import load_month_end_signal_dates, materialize_market_features
from data.piotroski_financial import (
    PIOTROSKI_ASOF_TABLE,
    PiotroskiFinancialPaths,
    attach_piotroski_financial_databases,
    create_piotroski_signal_date_table,
    materialize_piotroski_financial_asof,
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


EXPERIMENT_ID = "piotroski_data_feasibility_v1"
REPORT_PATH = Path("docs/research/piotroski-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
HIGH_SCORE_THRESHOLD = 8
MIN_COMPLETE_CANDIDATES = 200
MIN_HIGH_SCORE_CANDIDATES = 20
MIN_COMPLETE_MONTH_SHARE = 0.90
MIN_HIGH_SCORE_MONTH_SHARE = 0.80

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Piotroski F-Score 数据可行性 V1",
    category="data_feasibility",
    hypothesis="九项财务改善信号能否按公告日稳定覆盖 A 股月频截面",
    definition={
        "factor": {
            "name": "Piotroski F-Score",
            "components": 9,
            "annual_reports_only": True,
            "high_score_threshold": HIGH_SCORE_THRESHOLD,
            "requires_three_consecutive_visible_years": True,
        },
        "visibility": {
            "field": "f_ann_date",
            "rule": "each_statement_publish_date_lte_signal_date",
            "revision": "latest_visible_revision",
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_feasibility_gates": {
            "complete_candidate_floor": MIN_COMPLETE_CANDIDATES,
            "complete_month_share": MIN_COMPLETE_MONTH_SHARE,
            "high_score_candidate_floor": MIN_HIGH_SCORE_CANDIDATES,
            "high_score_month_share": MIN_HIGH_SCORE_MONTH_SHARE,
            "locked_period_uses_same_gates": True,
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
    """先登记确定性研究身份，再扫描财务大表。"""
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
    """计算标准可投股票池中的完整 F-Score 覆盖。"""
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
        create_piotroski_signal_date_table(connection, signal_dates)
        attach_piotroski_financial_databases(
            connection,
            PiotroskiFinancialPaths(
                paths.income_statement_path,
                paths.balance_sheet_path,
                paths.cashflow_statement_path,
            ),
        )
        materialize_piotroski_financial_asof(connection)
        monthly = load_monthly_coverage(connection)
        latest_distribution = load_latest_score_distribution(connection)
    finally:
        connection.close()

    result = evaluate_feasibility(monthly, latest_distribution, latest_date)
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_monthly_coverage(connection: Any) -> pd.DataFrame:
    """按统一可投股票池统计完整九项和高分样本数。"""
    return connection.execute(
        f"""
        SELECT
            f.trade_date AS signal_date,
            COUNT(*) FILTER(WHERE p.f_score IS NOT NULL) AS complete_count,
            COUNT(*) FILTER(WHERE p.f_score >= {HIGH_SCORE_THRESHOLD})
                AS high_score_count
        FROM features f
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN {PIOTROSKI_ASOF_TABLE} p
          ON f.trade_date = p.signal_date AND f.symbol = p.symbol
        WHERE f.trade_date IN (SELECT signal_date FROM piotroski_signal_dates)
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


def load_latest_score_distribution(connection: Any) -> dict[str, int]:
    """记录最新截面的分数分布，判断候选是否只靠少数异常样本。"""
    rows = connection.execute(
        f"""
        SELECT CAST(f_score AS INTEGER) AS f_score, COUNT(*) AS stock_count
        FROM {PIOTROSKI_ASOF_TABLE}
        WHERE signal_date = (
            SELECT MAX(signal_date) FROM {PIOTROSKI_ASOF_TABLE}
        )
          AND f_score IS NOT NULL
        GROUP BY f_score
        ORDER BY f_score
        """
    ).fetchall()
    return {str(score): int(count) for score, count in rows}


def evaluate_feasibility(
    monthly: pd.DataFrame,
    latest_distribution: dict[str, int],
    latest_date: str,
) -> dict[str, Any]:
    """使用预先冻结的全样本与锁定期覆盖门槛。"""
    if monthly.empty:
        raise ValueError("Piotroski 覆盖审计没有月末数据")
    data = monthly.copy()
    complete_ok = data["complete_count"].ge(MIN_COMPLETE_CANDIDATES)
    high_score_ok = data["high_score_count"].ge(MIN_HIGH_SCORE_CANDIDATES)
    locked = data[data["signal_date"].astype(str).ge(LOCKED_START)].copy()
    locked_complete_ok = locked["complete_count"].ge(MIN_COMPLETE_CANDIDATES)
    locked_high_score_ok = locked["high_score_count"].ge(MIN_HIGH_SCORE_CANDIDATES)
    complete_share = float(complete_ok.mean())
    high_score_share = float(high_score_ok.mean())
    locked_complete_share = float(
        locked_complete_ok.mean() if not locked.empty else 0.0
    )
    locked_high_score_share = float(
        locked_high_score_ok.mean() if not locked.empty else 0.0
    )
    checks = {
        "complete_month_share": complete_share >= MIN_COMPLETE_MONTH_SHARE,
        "high_score_month_share": high_score_share >= MIN_HIGH_SCORE_MONTH_SHARE,
        "locked_complete_month_share": (
            locked_complete_share >= MIN_COMPLETE_MONTH_SHARE
        ),
        "locked_high_score_month_share": (
            locked_high_score_share >= MIN_HIGH_SCORE_MONTH_SHARE
        ),
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(data)),
        "complete_count_median": float(data["complete_count"].median()),
        "high_score_count_median": float(data["high_score_count"].median()),
        "complete_month_share": complete_share,
        "high_score_month_share": high_score_share,
        "locked_complete_month_share": locked_complete_share,
        "locked_high_score_month_share": locked_high_score_share,
        "latest_score_distribution": latest_distribution,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档覆盖明细，确保相同定义不再重复探索。"""
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
            "九项 F-Score 覆盖稳定，可进入固定定义回测"
            if passed
            else "F-Score 完整覆盖不足，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "F-Score 可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成仅讨论数据可行性的审计报告。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# Piotroski F-Score 数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面：{result['signal_months']} 个。
- 完整九项候选中位数：{result['complete_count_median']:.0f}。
- F-Score >= {HIGH_SCORE_THRESHOLD} 候选中位数：
  {result['high_score_count_median']:.0f}。
- 全样本完整覆盖达标月份：{result['complete_month_share']:.2%}。
- 全样本高分覆盖达标月份：{result['high_score_month_share']:.2%}。
- 2022 年后完整/高分覆盖：
  {result['locked_complete_month_share']:.2%} /
  {result['locked_high_score_month_share']:.2%}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定三张财务表和行情快照版本。"""
    parts: list[str] = []
    for label, path in [
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
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
