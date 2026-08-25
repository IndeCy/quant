"""连续年报资产周转率改善因子的数据可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.asset_turnover_change import (
    ASSET_TURNOVER_CHANGE_TABLE,
    AssetTurnoverFinancialPaths,
    attach_asset_turnover_databases,
    create_asset_turnover_signal_dates,
    materialize_asset_turnover_change_asof,
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


EXPERIMENT_ID = "asset_turnover_change_data_feasibility_v1"
REPORT_PATH = Path("docs/research/asset-turnover-change-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
MIN_CANDIDATES = 500
MIN_UNIQUE_VALUES = 400
MIN_MONTH_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="资产周转率改善数据可行性 V1",
    category="data_feasibility",
    hypothesis="连续年报资产周转率变化能否稳定覆盖A股可投月频截面",
    definition={
        "factor": {
            "formula": (
                "revenue_t/avg_assets_t_minus_"
                "revenue_t_minus_1/avg_assets_t_minus_1"
            ),
            "annual_reports_only": True,
            "requires_three_consecutive_balance_sheets": True,
            "direction": "higher_is_better",
        },
        "visibility": {
            "rule": "each_statement_latest_visible_revision_lte_signal_date",
            "report_freshness_years": [1, 2],
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
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
    """先申请研究指纹，再读取财务和行情大表。"""
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
    """构造点时截面并执行冻结覆盖门槛。"""
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
        create_asset_turnover_signal_dates(connection, signal_dates)
        attach_asset_turnover_databases(
            connection,
            AssetTurnoverFinancialPaths(
                paths.income_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_asset_turnover_change_asof(connection)
        candidates = load_candidates(connection)
        monthly = build_monthly_coverage(candidates)
        distribution = build_latest_distribution(candidates)
        diagnostics = load_diagnostics(connection, candidates)
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


def load_candidates(connection: Any) -> pd.DataFrame:
    """读取严格过滤名称后的可投资产周转率截面。"""
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
                SELECT signal_date FROM asset_turnover_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            f.ret120,
            t.* EXCLUDE(signal_date, symbol)
        FROM features f
        JOIN {ASSET_TURNOVER_CHANGE_TABLE} t
          ON f.trade_date = t.signal_date AND f.symbol = t.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (
                SELECT signal_date FROM asset_turnover_signal_dates
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


def build_monthly_coverage(candidates: pd.DataFrame) -> pd.DataFrame:
    """按月统计有效样本数和连续值辨识度。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        values = pd.to_numeric(group["asset_turnover_change"], errors="coerce")
        rows.append(
            {
                "signal_date": str(signal_date),
                "candidate_count": int(values.notna().sum()),
                "unique_factor_values": int(values.nunique()),
                "positive_count": int(values.gt(0).sum()),
                "negative_count": int(values.lt(0).sum()),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(candidates: pd.DataFrame) -> dict[str, float]:
    """记录最新截面的变化值和周转率水平分布。"""
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]
    changes = pd.to_numeric(latest["asset_turnover_change"], errors="coerce")
    levels = pd.to_numeric(latest["asset_turnover"], errors="coerce")
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
    candidates: pd.DataFrame,
) -> dict[str, float]:
    """审计公告边界、主键唯一性和水平值相关性。"""
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
        FROM {ASSET_TURNOVER_CHANGE_TABLE}
        """
    ).fetchone()
    correlations: list[float] = []
    for _, group in candidates.groupby("signal_date", sort=True):
        valid = group.dropna(
            subset=["asset_turnover_change", "asset_turnover"]
        )
        correlation = valid["asset_turnover_change"].rank().corr(
            valid["asset_turnover"].rank()
        )
        if pd.notna(correlation):
            correlations.append(float(correlation))
    return {
        "visibility_violations": float(row[0] or 0),
        "duplicate_signal_symbol_rows": float(row[1] or 0),
        "median_spearman_with_turnover_level": float(
            pd.Series(correlations).median()
        ),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行冻结的覆盖、辨识度和点时门槛。"""
    if monthly.empty:
        raise ValueError("资产周转率改善覆盖审计没有月末数据")
    candidate_share = float(
        monthly["candidate_count"].ge(MIN_CANDIDATES).mean()
    )
    unique_share = float(
        monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES).mean()
    )
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_candidate_share = float(
        locked["candidate_count"].ge(MIN_CANDIDATES).mean()
        if not locked.empty
        else 0.0
    )
    locked_unique_share = float(
        locked["unique_factor_values"].ge(MIN_UNIQUE_VALUES).mean()
        if not locked.empty
        else 0.0
    )
    checks = {
        "candidate_month_share": candidate_share >= MIN_MONTH_SHARE,
        "unique_value_month_share": unique_share >= MIN_MONTH_SHARE,
        "locked_candidate_month_share": (
            locked_candidate_share >= MIN_MONTH_SHARE
        ),
        "locked_unique_value_month_share": (
            locked_unique_share >= MIN_MONTH_SHARE
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
        "unique_value_min": int(monthly["unique_factor_values"].min()),
        "unique_value_median": float(
            monthly["unique_factor_values"].median()
        ),
        "unique_value_latest": int(
            monthly["unique_factor_values"].iloc[-1]
        ),
        "candidate_month_share": candidate_share,
        "unique_value_month_share": unique_share,
        "locked_candidate_month_share": locked_candidate_share,
        "locked_unique_value_month_share": locked_unique_share,
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
    """归档数据审计，未通过时不得启动收益回测。"""
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
            "资产周转率改善数据覆盖和点时语义通过，可进入固定回测"
            if passed
            else "资产周转率改善未通过冻结数据门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成只讨论数据可行性的报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 资产周转率改善数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 总候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 唯一因子值最少/中位/最新：{result['unique_value_min']} /
  {result['unique_value_median']:.0f} / {result['unique_value_latest']}。
- 最新变化值 P1/中位/P99：{distribution['change_p01']:.4f} /
  {distribution['change_median']:.4f} / {distribution['change_p99']:.4f}。
- 最新周转率水平 P1/中位/P99：{distribution['level_p01']:.4f} /
  {distribution['level_median']:.4f} / {distribution['level_p99']:.4f}。
- 与周转率水平的月度 Spearman 中位数：
  {diagnostics['median_spearman_with_turnover_level']:.3f}。
- 公告日越界/重复主键：{diagnostics['visibility_violations']:.0f} /
  {diagnostics['duplicate_signal_symbol_rows']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定利润表、资产负债表和行情快照版本。"""
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
