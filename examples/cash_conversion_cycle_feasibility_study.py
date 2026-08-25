"""现金转换周期改善因子的点时数据可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.cash_conversion_cycle import (
    CASH_CONVERSION_CYCLE_TABLE,
    CashConversionFinancialPaths,
    attach_cash_conversion_databases,
    create_cash_conversion_signal_dates,
    materialize_cash_conversion_cycle_asof,
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


EXPERIMENT_ID = "cash_conversion_cycle_data_feasibility_v1"
REPORT_PATH = Path("docs/research/cash-conversion-cycle-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
MIN_CANDIDATES = 500
MIN_UNIQUE_VALUES = 400
MIN_COVERAGE = 0.50
MIN_MONTH_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="现金转换周期改善数据可行性 V1",
    category="data_feasibility",
    hypothesis="应收、存货和应付构成的现金转换周期变化能否稳定覆盖可投A股",
    definition={
        "factor": {
            "formula": "delta(DSO+DIO-DPO)",
            "direction": "lower_is_better",
            "days": {
                "DSO": "365*average_accounts_receivable/revenue",
                "DIO": "365*average_inventory/operating_cost",
                "DPO": "365*average_accounts_payable/operating_cost",
            },
            "missing_policy": "exclude_never_zero_fill",
            "requires_three_consecutive_annual_statements": True,
        },
        "visibility": {
            "rule": "each_statement_latest_visible_revision_lte_signal_date",
            "report_freshness_years": [1, 2],
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "complete_coverage_floor": MIN_COVERAGE,
            "month_share": MIN_MONTH_SHARE,
            "locked_period_same_gate": True,
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
    """先申请研究指纹，再读取两张财务大表。"""
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
    """物化点时财务截面并执行冻结数据门槛。"""
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
        create_cash_conversion_signal_dates(connection, signal_dates)
        attach_cash_conversion_databases(
            connection,
            CashConversionFinancialPaths(
                paths.income_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_cash_conversion_cycle_asof(connection)
        panel = load_investable_panel(connection)
        monthly = build_monthly_coverage(panel)
        distribution = build_latest_distribution(panel)
        diagnostics = load_diagnostics(connection, panel)
    finally:
        connection.close()
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


def load_investable_panel(connection: Any) -> pd.DataFrame:
    """保留完整可投分母，财务缺失记录不能静默消失。"""
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
            WHERE f.trade_date IN (
                SELECT signal_date FROM cash_conversion_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            f.ret120,
            c.* EXCLUDE(signal_date, symbol)
        FROM features f
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        LEFT JOIN {CASH_CONVERSION_CYCLE_TABLE} c
          ON f.trade_date = c.signal_date AND f.symbol = c.symbol
        WHERE f.trade_date IN (
                SELECT signal_date FROM cash_conversion_signal_dates
              )
          AND f.st_name IS NULL
          AND NOT REGEXP_MATCHES(COALESCE(na.asof_name, sb.name, ''), 'ST|退')
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def load_candidates(connection: Any) -> pd.DataFrame:
    """正式研究只消费字段完整且可计算的现金转换周期。"""
    panel = load_investable_panel(connection)
    values = pd.to_numeric(
        panel["cash_conversion_cycle_change"],
        errors="coerce",
    )
    return panel.loc[values.notna()].copy()


def build_monthly_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """统计完整样本占标准可投股票池的比例。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in panel.groupby("signal_date", sort=True):
        values = pd.to_numeric(
            group["cash_conversion_cycle_change"],
            errors="coerce",
        )
        candidate_count = int(values.notna().sum())
        rows.append(
            {
                "signal_date": str(signal_date),
                "investable_count": int(len(group)),
                "candidate_count": candidate_count,
                "coverage": candidate_count / len(group),
                "unique_factor_values": int(values.nunique()),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(panel: pd.DataFrame) -> dict[str, float]:
    """记录最新截面周期水平和变化分布。"""
    latest = panel[panel["signal_date"].eq(panel["signal_date"].max())]
    changes = pd.to_numeric(
        latest["cash_conversion_cycle_change"],
        errors="coerce",
    )
    levels = pd.to_numeric(latest["cash_conversion_cycle"], errors="coerce")
    return {
        "change_p01": float(changes.quantile(0.01)),
        "change_median": float(changes.median()),
        "change_p99": float(changes.quantile(0.99)),
        "level_p01": float(levels.quantile(0.01)),
        "level_median": float(levels.median()),
        "level_p99": float(levels.quantile(0.99)),
    }


def load_diagnostics(
    connection: Any,
    panel: pd.DataFrame,
) -> dict[str, float]:
    """审计公告边界、主键唯一性和缺失来源。"""
    row = connection.execute(
        f"""
        SELECT
            SUM(CASE WHEN publish_date > signal_date
                       OR income_publish_date > signal_date
                       OR balance_publish_date > signal_date
                       OR prior_publish_date > signal_date
                       OR prior2_publish_date > signal_date
                     THEN 1 ELSE 0 END),
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol)
        FROM {CASH_CONVERSION_CYCLE_TABLE}
        """
    ).fetchone()
    financial = panel["report_period"].notna()
    component_missing = panel["required_component_missing"].fillna(True)
    return {
        "visibility_violations": float(row[0] or 0),
        "duplicate_signal_symbol_rows": float(row[1] or 0),
        "financial_snapshot_missing_share": float((~financial).mean()),
        "required_component_missing_share": float(component_missing.mean()),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行冻结覆盖、辨识度和点时门槛。"""
    if monthly.empty:
        raise ValueError("现金转换周期覆盖审计没有月末数据")
    checks_by_row = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["coverage"].ge(MIN_COVERAGE)
    )
    full_share = float(checks_by_row.mean())
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_checks = (
        locked["candidate_count"].ge(MIN_CANDIDATES)
        & locked["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & locked["coverage"].ge(MIN_COVERAGE)
    )
    locked_share = float(locked_checks.mean() if not locked.empty else 0.0)
    checks = {
        "full_qualified_month_share": full_share >= MIN_MONTH_SHARE,
        "locked_qualified_month_share": locked_share >= MIN_MONTH_SHARE,
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
        "investable_count_min": int(monthly["investable_count"].min()),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "coverage_min": float(monthly["coverage"].min()),
        "coverage_median": float(monthly["coverage"].median()),
        "coverage_latest": float(monthly["coverage"].iloc[-1]),
        "unique_value_min": int(monthly["unique_factor_values"].min()),
        "full_qualified_month_share": full_share,
        "locked_qualified_month_share": locked_share,
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
    """归档数据审计，未通过时不得启动回测。"""
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
            "现金转换周期覆盖和点时语义通过，可进入固定回测"
            if passed
            else "现金转换周期未通过冻结数据门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成现金转换周期数据可行性报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 现金转换周期改善数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 完整候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 完整覆盖率最少/中位/最新：{result['coverage_min']:.2%} /
  {result['coverage_median']:.2%} / {result['coverage_latest']:.2%}。
- 最新周期变化 P1/中位/P99：{distribution['change_p01']:.2f} /
  {distribution['change_median']:.2f} / {distribution['change_p99']:.2f} 天。
- 最新周期水平 P1/中位/P99：{distribution['level_p01']:.2f} /
  {distribution['level_median']:.2f} / {distribution['level_p99']:.2f} 天。
- 财务快照缺失/必需字段缺失：
  {diagnostics['financial_snapshot_missing_share']:.2%} /
  {diagnostics['required_component_missing_share']:.2%}。
- 公告越界/重复主键：{diagnostics['visibility_violations']:.0f} /
  {diagnostics['duplicate_signal_symbol_rows']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定利润表、资产负债表和行情数据版本。"""
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
