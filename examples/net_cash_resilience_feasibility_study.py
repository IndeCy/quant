"""净现金财务韧性因子的数据与可交易性审计。"""

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
from data.net_cash_resilience import (
    NET_CASH_RESILIENCE_TABLE,
    NetCashResiliencePaths,
    attach_net_cash_database,
    create_net_cash_signal_date_table,
    materialize_net_cash_resilience_asof,
)
from factors.net_cash_resilience import score_net_cash_resilience_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "net_cash_resilience_data_feasibility_v1"
REPORT_PATH = Path("docs/research/net-cash-resilience-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20240101"
TOP_N = 40
MIN_CANDIDATES = 1000
MIN_UNIQUE_VALUES = 800
MIN_MONTH_SHARE = 0.90
MAX_TOP40_UNREPORTED_DEBT_SHARE = 0.20
MIN_TOP40_MEDIAN_ADV_RMB = 10_000_000.0
MIN_TOP40_ADV_RMB = 5_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="净现金财务韧性数据可行性 V1",
    category="data_feasibility",
    hypothesis="净现金资产比能否形成点时可信、可辨识且可交易的月频截面",
    definition={
        "factor": {
            "formula": (
                "(money_cap-sum(st_borr,lt_borr,bond_payable,"
                "non_cur_liab_due_1y,st_fin_payable,lease_liab))/total_assets"
            ),
            "direction": "higher_is_better",
            "null_debt_treatment": "coalesce_zero_with_explicit_coverage_audit",
            "valid_range": [-5.0, 1.05],
        },
        "visibility": {
            "annual_reports_only": True,
            "publish_date": "balance_sheet_f_ann_date",
            "publish_date_lte_signal_date": True,
            "latest_fiscal_year_age": [1, 2],
            "general_industrial_company_only": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "tradability": {
            "reference_capital": 5_000_000,
            "top_n": TOP_N,
            "median_adv_floor_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "single_name_adv_floor_rmb": MIN_TOP40_ADV_RMB,
            "minimum_name_share_above_floor": MIN_TOP40_TRADABLE_SHARE,
        },
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_MONTH_SHARE,
            "locked_period_same_gate": True,
            "maximum_top40_unreported_debt_share": (
                MAX_TOP40_UNREPORTED_DEBT_SHARE
            ),
            "duplicate_signal_symbol_rows": 0,
            "visibility_violations": 0,
            "range_violations": 0,
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
    """先申请研究指纹，再读取行情和资产负债表。"""
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
    """物化净现金截面并执行冻结门槛。"""
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
        create_net_cash_signal_date_table(connection, signal_dates)
        attach_net_cash_database(
            connection,
            NetCashResiliencePaths(paths.balance_sheet_path),
        )
        materialize_net_cash_resilience_asof(connection)
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
    """连接标准可投股票池、净现金截面和行情归因字段。"""
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
            WHERE f.trade_date IN (SELECT signal_date FROM net_cash_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            n.report_period,
            n.publish_date,
            n.cash_and_equivalents,
            n.interest_bearing_debt,
            n.total_assets,
            n.net_cash_to_assets,
            n.reported_debt_item_count,
            f.amount20 * 1000.0 AS amount20_rmb,
            f.vol60,
            f.ret120
        FROM features f
        JOIN {NET_CASH_RESILIENCE_TABLE} n
          ON f.trade_date = n.signal_date AND f.symbol = n.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.st_name IS NULL
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


def build_monthly_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """统计覆盖、债务字段语义和拟选 Top40 成交能力。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in panel.groupby("signal_date", sort=True):
        scored = score_net_cash_resilience_frame(group)
        top = scored.nlargest(TOP_N, "factor_score")
        rows.append(
            {
                "signal_date": str(signal_date),
                "candidate_count": int(len(scored)),
                "unique_factor_values": int(
                    scored["net_cash_to_assets"].nunique()
                ),
                "top40_unreported_debt_share": float(
                    top["reported_debt_item_count"].eq(0).mean()
                ),
                "top40_median_adv_rmb": float(top["amount20_rmb"].median()),
                "top40_tradable_share": float(
                    top["amount20_rmb"].ge(MIN_TOP40_ADV_RMB).mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(panel: pd.DataFrame) -> dict[str, float]:
    """记录最新截面的因子与债务字段覆盖分布。"""
    latest = panel[panel["signal_date"].eq(panel["signal_date"].max())]
    latest = score_net_cash_resilience_frame(latest)
    return {
        "ratio_p01": float(latest["net_cash_to_assets"].quantile(0.01)),
        "ratio_median": float(latest["net_cash_to_assets"].median()),
        "ratio_p99": float(latest["net_cash_to_assets"].quantile(0.99)),
        "unreported_debt_share": float(
            latest["reported_debt_item_count"].eq(0).mean()
        ),
        "zero_interest_debt_share": float(
            latest["interest_bearing_debt"].eq(0).mean()
        ),
    }


def load_diagnostics(
    connection: Any,
    panel: pd.DataFrame,
) -> dict[str, float]:
    """检查点时性、范围和与常见价格风格的相关性。"""
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol),
            SUM(CASE WHEN publish_date > signal_date THEN 1 ELSE 0 END),
            SUM(
                CASE WHEN net_cash_to_assets < -5.0
                       OR net_cash_to_assets > 1.05
                     THEN 1 ELSE 0 END
            )
        FROM {NET_CASH_RESILIENCE_TABLE}
        """
    ).fetchone()
    correlations: dict[str, list[float]] = {
        "amount20_rmb": [],
        "vol60": [],
        "ret120": [],
    }
    for _, group in panel.groupby("signal_date", sort=True):
        scored = score_net_cash_resilience_frame(group)
        factor_rank = scored["factor_score"].rank()
        for field in correlations:
            value = factor_rank.corr(scored[field].rank())
            if pd.notna(value):
                correlations[field].append(float(value))
    return {
        "duplicate_signal_symbol_rows": float(row[0] or 0),
        "visibility_violations": float(row[1] or 0),
        "range_violations": float(row[2] or 0),
        "median_spearman_with_amount20": _median(
            correlations["amount20_rmb"]
        ),
        "median_spearman_with_vol60": _median(correlations["vol60"]),
        "median_spearman_with_ret120": _median(correlations["ret120"]),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行覆盖、债务字段和个人资金可交易性门槛。"""
    if monthly.empty:
        raise ValueError("净现金覆盖审计没有月末数据")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_unreported_debt_share"].le(
            MAX_TOP40_UNREPORTED_DEBT_SHARE
        )
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_qualified = qualified.loc[locked.index]
    full_share = float(qualified.mean())
    locked_share = float(
        locked_qualified.mean() if not locked.empty else 0.0
    )
    checks = {
        "full_qualified_month_share": full_share >= MIN_MONTH_SHARE,
        "locked_qualified_month_share": locked_share >= MIN_MONTH_SHARE,
        "zero_duplicate_signal_symbol_rows": (
            diagnostics["duplicate_signal_symbol_rows"] == 0
        ),
        "zero_visibility_violations": diagnostics["visibility_violations"] == 0,
        "zero_range_violations": diagnostics["range_violations"] == 0,
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
        "unique_value_min": int(monthly["unique_factor_values"].min()),
        "maximum_top40_unreported_debt_share": float(
            monthly["top40_unreported_debt_share"].max()
        ),
        "minimum_top40_median_adv_rmb": float(
            monthly["top40_median_adv_rmb"].min()
        ),
        "minimum_top40_tradable_share": float(
            monthly["top40_tradable_share"].min()
        ),
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
    """归档可行性结论与月度覆盖明细。"""
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
            "净现金数据、债务字段和成交能力通过，可进入固定回测"
            if passed
            else "净现金未通过冻结数据或成交门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成净现金数据可行性报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 净现金财务韧性数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 唯一因子值最少：{result['unique_value_min']}；
  Top40债务字段全部未报告占比最大值：
  {result['maximum_top40_unreported_debt_share']:.1%}。
- Top40月度日均成交额中位数最低值：
  {result['minimum_top40_median_adv_rmb'] / 1e6:.1f}百万元；
  高于500万元的持仓比例最低值：
  {result['minimum_top40_tradable_share']:.1%}。
- 最新净现金资产比 P1/中位/P99：
  {distribution['ratio_p01']:.3f} /
  {distribution['ratio_median']:.3f} /
  {distribution['ratio_p99']:.3f}。
- 最新全债务字段未报告/有息债务为零占比：
  {distribution['unreported_debt_share']:.1%} /
  {distribution['zero_interest_debt_share']:.1%}。
- 与20日成交额/60日波动/120日收益 Spearman 中位数：
  {diagnostics['median_spearman_with_amount20']:.3f} /
  {diagnostics['median_spearman_with_vol60']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 重复主键/未来可见/范围异常：
  {diagnostics['duplicate_signal_symbol_rows']:.0f} /
  {diagnostics['visibility_violations']:.0f} /
  {diagnostics['range_violations']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段没有运行收益回测，也没有注册生产策略。
"""


def _median(values: list[float]) -> float:
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情与资产负债表文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("balance", paths.balance_sheet_path),
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
