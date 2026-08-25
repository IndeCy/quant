"""Fama-French 经营盈利能力因子的点时数据可行性审计。"""

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
from data.operating_profitability import (
    OPERATING_PROFITABILITY_TABLE,
    OperatingProfitabilityPaths,
    attach_operating_profitability_databases,
    create_operating_profitability_signal_dates,
    materialize_operating_profitability_asof,
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


EXPERIMENT_ID = "operating_profitability_data_feasibility_v1"
REPORT_PATH = Path("docs/research/operating-profitability-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
MIN_CANDIDATES = 500
MIN_MONTH_SHARE = 0.90
MAX_COMPONENT_MISSING_SHARE = 0.60
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="经营盈利能力数据可行性 V1",
    category="data_feasibility",
    hypothesis="Fama-French经营盈利能力能否用已披露年报稳定构造A股月频截面",
    definition={
        "factor": {
            "formula": (
                "(revenue-oper_cost-sell_exp-admin_exp-interest_expense)"
                "/total_hldr_eqy_inc_min_int"
            ),
            "interest_expense": "coalesce(fin_exp_int_exp,int_exp,0)",
            "missing_sell_admin_interest": "zero_with_missingness_audit",
            "annual_reports_only": True,
        },
        "visibility": {
            "rule": "each_statement_latest_revision_f_ann_date_lte_signal_date",
            "report_freshness_years": [1, 2],
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "month_share": MIN_MONTH_SHARE,
            "component_missing_share_max": MAX_COMPONENT_MISSING_SHARE,
            "visibility_violations": 0,
            "duplicate_signal_symbol_rows": 0,
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
    """先登记研究指纹，再读取两张财务大表。"""
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
    """统计统一可投股票池的月度覆盖和字段完整度。"""
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
        create_operating_profitability_signal_dates(connection, signal_dates)
        attach_operating_profitability_databases(
            connection,
            OperatingProfitabilityPaths(
                paths.income_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_operating_profitability_asof(connection)
        candidates = load_candidates(connection)
        diagnostics = load_diagnostics(connection, candidates)
    finally:
        connection.close()

    monthly = (
        candidates.groupby("signal_date", as_index=False)
        .size()
        .rename(columns={"size": "candidate_count"})
    )
    result = evaluate_feasibility(monthly, diagnostics, latest_date)
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_candidates(connection: Any) -> pd.DataFrame:
    """读取满足上市、状态、流动性和财报新鲜度要求的候选。"""
    return connection.execute(
        f"""
        WITH name_history AS (
            SELECT ts_code, name, start_date, end_date FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date FROM stock_name_manual
        ),
        name_asof AS (
            SELECT
                f.trade_date AS signal_date,
                f.symbol,
                h.name AS asof_name,
                ROW_NUMBER() OVER(
                    PARTITION BY f.trade_date, f.symbol
                    ORDER BY h.start_date DESC
                ) AS rn
            FROM features f
            JOIN name_history h ON f.symbol = h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (SELECT signal_date FROM op_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            sb.list_date,
            sb.delist_date,
            f.close,
            f.ret120,
            f.amount,
            f.amount_p20,
            op.*
                EXCLUDE(signal_date, symbol)
        FROM features f
        JOIN {OPERATING_PROFITABILITY_TABLE} op
          ON f.trade_date = op.signal_date AND f.symbol = op.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM op_signal_dates)
          AND f.st_name IS NULL
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
          AND NOT REGEXP_MATCHES(COALESCE(na.asof_name, sb.name, ''), 'ST|退')
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def load_diagnostics(
    connection: Any,
    candidates: pd.DataFrame,
) -> dict[str, float]:
    """统计可见性、重复、量纲和费用字段缺失。"""
    visibility, duplicates = connection.execute(
        f"""
        SELECT
            SUM(
                CASE WHEN publish_date > signal_date
                    OR income_publish_date > signal_date
                    OR balance_publish_date > signal_date
                THEN 1 ELSE 0 END
            ),
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol)
        FROM {OPERATING_PROFITABILITY_TABLE}
        """
    ).fetchone()
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]
    values = pd.to_numeric(latest["operating_profitability"], errors="coerce")
    return {
        "visibility_violations": float(visibility or 0),
        "duplicate_signal_symbol_rows": float(duplicates or 0),
        "selling_expense_missing_share": float(
            candidates["selling_expense_missing"].mean()
        ),
        "admin_expense_missing_share": float(
            candidates["admin_expense_missing"].mean()
        ),
        "interest_expense_missing_share": float(
            candidates["interest_expense_missing"].mean()
        ),
        "latest_p01": float(values.quantile(0.01)),
        "latest_median": float(values.median()),
        "latest_p99": float(values.quantile(0.99)),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行研究前冻结的数据覆盖门槛。"""
    if monthly.empty:
        raise ValueError("经营盈利能力覆盖审计没有有效月末数据")
    full_share = float(monthly["candidate_count"].ge(MIN_CANDIDATES).mean())
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_share = float(
        locked["candidate_count"].ge(MIN_CANDIDATES).mean()
        if not locked.empty
        else 0.0
    )
    checks = {
        "full_candidate_month_share": full_share >= MIN_MONTH_SHARE,
        "locked_candidate_month_share": locked_share >= MIN_MONTH_SHARE,
        "zero_visibility_violations": (
            diagnostics["visibility_violations"] == 0
        ),
        "zero_duplicate_signal_symbol_rows": (
            diagnostics["duplicate_signal_symbol_rows"] == 0
        ),
        "selling_expense_missing_within_limit": (
            diagnostics["selling_expense_missing_share"]
            <= MAX_COMPONENT_MISSING_SHARE
        ),
        "admin_expense_missing_within_limit": (
            diagnostics["admin_expense_missing_share"]
            <= MAX_COMPONENT_MISSING_SHARE
        ),
        "interest_expense_missing_within_limit": (
            diagnostics["interest_expense_missing_share"]
            <= MAX_COMPONENT_MISSING_SHARE
        ),
        "finite_latest_distribution": all(
            pd.notna(diagnostics[key])
            for key in ("latest_p01", "latest_median", "latest_p99")
        ),
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "full_candidate_month_share": full_share,
        "locked_candidate_month_share": locked_share,
        "diagnostics": diagnostics,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档覆盖明细，数据不可信时不进入收益回测。"""
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
            "经营盈利能力数据覆盖和点时语义通过，可进入固定回测"
            if passed
            else "经营盈利能力数据未通过冻结门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "经营盈利能力可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成不包含收益结果的数据可行性报告。"""
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 经营盈利能力数据可行性 V1

- 数据截止：{result['latest_date']}，共 {result['signal_months']} 个月末截面。
- 候选数最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 全样本/2022年后达标月份：{result['full_candidate_month_share']:.2%} /
  {result['locked_candidate_month_share']:.2%}。
- 公告日越界/重复记录：{diagnostics['visibility_violations']:.0f} /
  {diagnostics['duplicate_signal_symbol_rows']:.0f}。
- 销售/管理/利息费用缺失率：
  {diagnostics['selling_expense_missing_share']:.2%} /
  {diagnostics['admin_expense_missing_share']:.2%} /
  {diagnostics['interest_expense_missing_share']:.2%}。
- 最新因子 P1/中位/P99：{diagnostics['latest_p01']:.4f} /
  {diagnostics['latest_median']:.4f} / {diagnostics['latest_p99']:.4f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定两张财务表和行情快照版本。"""
    parts: list[str] = []
    for label, path in [
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
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
