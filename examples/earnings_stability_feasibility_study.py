"""五年盈利稳定性因子的数据可行性审计。"""

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
from data.profitability_history import (
    PROFITABILITY_FLOOR_ASOF_TABLE,
    ProfitabilityHistoryPaths,
    attach_profitability_history_databases,
    create_profitability_signal_date_table,
    materialize_profitability_floor_asof,
)
from factors.earnings_stability import score_earnings_stability_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "earnings_stability_data_feasibility_v1"
REPORT_PATH = Path("docs/research/earnings-stability-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20240101"
MIN_CANDIDATES = 800
MIN_UNIQUE_VALUES = 700
MIN_MONTH_SHARE = 0.90
MAX_ZERO_STD_SHARE = 0.05
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="五年盈利稳定性数据可行性 V1",
    category="data_feasibility",
    hypothesis="低五年ROA波动能否形成覆盖稳定、可辨识的全A月频截面",
    definition={
        "factor": {
            "formula": "stddev_samp(roa,latest_5_consecutive_annual_reports)",
            "direction": "lower_is_better",
            "eligibility": "mean_roa_5y_positive",
            "mean_roa_role": "stable_loss_exclusion_only_not_rank_factor",
        },
        "visibility": {
            "annual_reports_only": True,
            "publish_date": "max_income_balance_cashflow_f_ann_date",
            "publish_date_lte_signal_date": True,
            "latest_fiscal_year_age": [1, 2],
            "consecutive_fiscal_years_required": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_MONTH_SHARE,
            "locked_period_same_gate": True,
            "maximum_zero_std_share": MAX_ZERO_STD_SHARE,
            "duplicate_signal_symbol_rows": 0,
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
    """先申请研究指纹，再读取行情和财务大表。"""
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
    """物化五年年报窗口并执行冻结的数据门槛。"""
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
        create_profitability_signal_date_table(connection, signal_dates)
        attach_profitability_history_databases(
            connection,
            ProfitabilityHistoryPaths(
                indicator=paths.fina_indicator_path,
                income=paths.income_statement_path,
                balance=paths.balance_sheet_path,
                cashflow=paths.cashflow_statement_path,
            ),
        )
        materialize_profitability_floor_asof(connection)
        panel = load_earnings_stability_candidates(connection)
        monthly = build_monthly_coverage(panel)
        distribution = build_latest_distribution(panel)
        diagnostics = load_diagnostics(panel)
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


def load_earnings_stability_candidates(connection: Any) -> pd.DataFrame:
    """连接标准可投股票池、长期盈利截面与行情归因字段。"""
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
                SELECT signal_date FROM profitability_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            p.latest_fiscal_year,
            p.latest_publish_date,
            p.current_roa,
            p.roa_floor_5y,
            p.roa_mean_5y,
            p.roa_std_5y,
            p.observations,
            f.vol60,
            f.ret120
        FROM features f
        JOIN {PROFITABILITY_FLOOR_ASOF_TABLE} p
          ON f.trade_date = p.signal_date AND f.symbol = p.symbol
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
    """统计每月正平均盈利候选、辨识度和零波动占比。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in panel.groupby("signal_date", sort=True):
        scored = score_earnings_stability_frame(group)
        rows.append(
            {
                "signal_date": str(signal_date),
                "candidate_count": int(len(scored)),
                "unique_factor_values": int(scored["roa_std_5y"].nunique()),
                "zero_std_share": float(
                    scored["roa_std_5y"].eq(0).mean()
                    if not scored.empty
                    else 1.0
                ),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(panel: pd.DataFrame) -> dict[str, float]:
    """记录最新截面的波动、均值和当前盈利分布。"""
    latest = panel[panel["signal_date"].eq(panel["signal_date"].max())]
    latest = score_earnings_stability_frame(latest)
    return {
        "std_p01": float(latest["roa_std_5y"].quantile(0.01)),
        "std_median": float(latest["roa_std_5y"].median()),
        "std_p99": float(latest["roa_std_5y"].quantile(0.99)),
        "mean_roa_median": float(latest["roa_mean_5y"].median()),
        "current_roa_median": float(latest["current_roa"].median()),
    }


def load_diagnostics(panel: pd.DataFrame) -> dict[str, float]:
    """检查主键、公告可见性、窗口长度和水平因子污染。"""
    duplicate_rows = len(panel) - len(
        panel.drop_duplicates(["signal_date", "symbol"])
    )
    visibility = (
        panel["latest_publish_date"].astype(str)
        > panel["signal_date"].astype(str)
    ).sum()
    correlations: list[float] = []
    for _, group in panel.groupby("signal_date", sort=True):
        scored = score_earnings_stability_frame(group)
        correlation = scored["factor_score"].corr(
            scored["roa_mean_5y"].rank(pct=True)
        )
        if pd.notna(correlation):
            correlations.append(float(correlation))
    return {
        "duplicate_signal_symbol_rows": float(duplicate_rows),
        "visibility_violations": float(visibility),
        "observation_count_violations": float(
            panel["observations"].ne(5).sum()
        ),
        "median_spearman_score_with_mean_roa": float(
            pd.Series(correlations).median()
        ),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行覆盖、辨识度、点时性和数值门槛。"""
    if monthly.empty:
        raise ValueError("盈利稳定性覆盖审计没有月末数据")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["zero_std_share"].le(MAX_ZERO_STD_SHARE)
    )
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_qualified = (
        locked["candidate_count"].ge(MIN_CANDIDATES)
        & locked["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & locked["zero_std_share"].le(MAX_ZERO_STD_SHARE)
    )
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
        "zero_observation_count_violations": (
            diagnostics["observation_count_violations"] == 0
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
        "maximum_zero_std_share": float(monthly["zero_std_share"].max()),
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
    """归档数据审计，失败时保留研究指纹。"""
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
            "盈利稳定性数据覆盖稳定，可进入固定回测"
            if passed
            else "盈利稳定性未通过冻结数据门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成盈利稳定性数据可行性报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 五年盈利稳定性数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 唯一因子值最少：{result['unique_value_min']}；
  零标准差占比最大值：{result['maximum_zero_std_share']:.2%}。
- 最新 ROA 标准差 P1/中位/P99：{distribution['std_p01']:.3f} /
  {distribution['std_median']:.3f} / {distribution['std_p99']:.3f}。
- 最新五年平均/当前 ROA 中位数：
  {distribution['mean_roa_median']:.2f} /
  {distribution['current_roa_median']:.2f}。
- 稳定性得分与五年平均 ROA 的月度 Spearman 中位数：
  {diagnostics['median_spearman_score_with_mean_roa']:.3f}。
- 重复主键/未来可见/窗口长度异常：
  {diagnostics['duplicate_signal_symbol_rows']:.0f} /
  {diagnostics['visibility_violations']:.0f} /
  {diagnostics['observation_count_violations']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情与四张财务源文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("indicator", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
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
