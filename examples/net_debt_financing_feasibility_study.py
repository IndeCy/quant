"""一般工商业净债务融资因子的点时数据可行性审计。"""

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
from data.net_debt_financing import (
    NET_DEBT_FINANCING_TABLE,
    NetDebtFinancingPaths,
    attach_net_debt_financing_databases,
    create_net_debt_financing_signal_dates,
    materialize_net_debt_financing_asof,
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


EXPERIMENT_ID = "net_debt_financing_data_feasibility_v1"
REPORT_PATH = Path("docs/research/net-debt-financing-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
MIN_CANDIDATES = 500
MIN_NEGATIVE_CANDIDATES = 40
MIN_MONTH_SHARE = 0.90
MAX_ALL_COMPONENTS_MISSING_SHARE = 0.20
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="净债务融资数据可行性 V1",
    category="data_feasibility",
    hypothesis="一般工商业净偿债现金流能否稳定形成独立月频候选池",
    definition={
        "factor": {
            "formula": (
                "(c_recp_borrow+proc_issue_bonds-c_prepay_amt_borr)"
                "/total_assets"
            ),
            "direction": "lower_is_better",
            "missing_components": "zero_with_missingness_audit",
            "annual_reports_only": True,
        },
        "visibility": {
            "each_statement_latest_revision_f_ann_date_lte_signal_date": True,
            "report_types": ["1", "4"],
            "report_freshness_years": [1, 2],
        },
        "company_type": "1_general_industry",
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "negative_candidate_floor": MIN_NEGATIVE_CANDIDATES,
            "month_share": MIN_MONTH_SHARE,
            "all_components_missing_share_max": (
                MAX_ALL_COMPONENTS_MISSING_SHARE
            ),
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
    """先登记指纹，再读取现金流和资产负债表。"""
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
    """检查标准股票池内的点时覆盖、缺失和可辨识性。"""
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
        create_net_debt_financing_signal_dates(connection, signal_dates)
        attach_net_debt_financing_databases(
            connection,
            NetDebtFinancingPaths(
                paths.cashflow_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_net_debt_financing_asof(connection)
        candidates = load_candidates(connection)
        diagnostics = load_diagnostics(connection, candidates)
    finally:
        connection.close()

    monthly = build_monthly_coverage(candidates)
    distribution = build_latest_distribution(candidates)
    result = evaluate_feasibility(
        monthly,
        distribution,
        diagnostics,
        latest_date,
    )
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_candidates(connection: Any) -> pd.DataFrame:
    """读取可交易的一般工商业净债务融资截面。"""
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
            WHERE f.trade_date IN (SELECT signal_date FROM debt_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            f.ret120,
            d.* EXCLUDE(signal_date, symbol)
        FROM features f
        JOIN {NET_DEBT_FINANCING_TABLE} d
          ON f.trade_date = d.signal_date AND f.symbol = d.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM debt_signal_dates)
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
    """统计公告边界、重复和现金流字段缺失。"""
    row = connection.execute(
        f"""
        SELECT
            SUM(CASE WHEN publish_date > signal_date
                       OR cashflow_publish_date > signal_date
                       OR balance_publish_date > signal_date
                     THEN 1 ELSE 0 END),
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol)
        FROM {NET_DEBT_FINANCING_TABLE}
        """
    ).fetchone()
    return {
        "visibility_violations": float(row[0] or 0),
        "duplicate_signal_symbol_rows": float(row[1] or 0),
        "borrowing_cash_missing_share": float(
            candidates["borrowing_cash_missing"].mean()
        ),
        "bond_issue_cash_missing_share": float(
            candidates["bond_issue_cash_missing"].mean()
        ),
        "debt_repayment_cash_missing_share": float(
            candidates["debt_repayment_cash_missing"].mean()
        ),
        "all_components_missing_share": float(
            candidates["all_debt_cashflow_missing"].mean()
        ),
    }


def build_monthly_coverage(candidates: pd.DataFrame) -> pd.DataFrame:
    """统计总候选和净偿债候选数量。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        values = pd.to_numeric(group["net_debt_financing"], errors="coerce")
        rows.append(
            {
                "signal_date": str(signal_date),
                "candidate_count": int(values.notna().sum()),
                "negative_candidate_count": int(values.lt(-1e-12).sum()),
                "zero_candidate_count": int(values.abs().le(1e-12).sum()),
                "positive_candidate_count": int(values.gt(1e-12).sum()),
                "unique_factor_values": int(values.nunique()),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(candidates: pd.DataFrame) -> dict[str, float]:
    """记录最新截面净债务融资强度分布。"""
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]
    values = pd.to_numeric(latest["net_debt_financing"], errors="coerce")
    return {
        "p01": float(values.quantile(0.01)),
        "median": float(values.median()),
        "p99": float(values.quantile(0.99)),
        "zero_share": float(values.abs().le(1e-12).mean()),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行冻结覆盖、可辨识性和缺失率门槛。"""
    if monthly.empty:
        raise ValueError("净债务融资覆盖审计没有月末数据")
    candidate_share = float(
        monthly["candidate_count"].ge(MIN_CANDIDATES).mean()
    )
    negative_share = float(
        monthly["negative_candidate_count"]
        .ge(MIN_NEGATIVE_CANDIDATES)
        .mean()
    )
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_negative_share = float(
        locked["negative_candidate_count"]
        .ge(MIN_NEGATIVE_CANDIDATES)
        .mean()
        if not locked.empty
        else 0.0
    )
    checks = {
        "candidate_month_share": candidate_share >= MIN_MONTH_SHARE,
        "negative_candidate_month_share": negative_share >= MIN_MONTH_SHARE,
        "locked_negative_candidate_month_share": (
            locked_negative_share >= MIN_MONTH_SHARE
        ),
        "all_components_missing_within_limit": (
            diagnostics["all_components_missing_share"]
            <= MAX_ALL_COMPONENTS_MISSING_SHARE
        ),
        "zero_visibility_violations": diagnostics["visibility_violations"] == 0,
        "zero_duplicate_signal_symbol_rows": (
            diagnostics["duplicate_signal_symbol_rows"] == 0
        ),
        "finite_latest_distribution": all(
            pd.notna(value) for value in distribution.values()
        ),
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "negative_count_min": int(monthly["negative_candidate_count"].min()),
        "negative_count_median": float(
            monthly["negative_candidate_count"].median()
        ),
        "negative_count_latest": int(
            monthly["negative_candidate_count"].iloc[-1]
        ),
        "candidate_month_share": candidate_share,
        "negative_candidate_month_share": negative_share,
        "locked_negative_candidate_month_share": locked_negative_share,
        "latest_distribution": distribution,
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
    """归档数据审计，未过门槛时不启动收益回测。"""
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
            "净债务融资数据和可辨识性通过，可进入固定回测"
            if passed
            else "净债务融资未通过冻结数据门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "净债务融资可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成净债务融资数据可行性报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 净债务融资数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 总候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 净偿债候选最少/中位/最新：{result['negative_count_min']} /
  {result['negative_count_median']:.0f} / {result['negative_count_latest']}。
- 全样本/2022年后可组成Top40月份：
  {result['negative_candidate_month_share']:.2%} /
  {result['locked_negative_candidate_month_share']:.2%}。
- 最新 P1/中位/P99：{distribution['p01']:.2%} /
  {distribution['median']:.2%} / {distribution['p99']:.2%}；
  零值占比 {distribution['zero_share']:.2%}。
- 借款/发债/偿债字段缺失率：
  {diagnostics['borrowing_cash_missing_share']:.2%} /
  {diagnostics['bond_issue_cash_missing_share']:.2%} /
  {diagnostics['debt_repayment_cash_missing_share']:.2%}。
- 三项全缺失：{diagnostics['all_components_missing_share']:.2%}；
  公告越界/重复：{diagnostics['visibility_violations']:.0f} /
  {diagnostics['duplicate_signal_symbol_rows']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定现金流、资产负债表和行情数据版本。"""
    parts: list[str] = []
    for label, path in [
        ("cashflow", paths.cashflow_statement_path),
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
