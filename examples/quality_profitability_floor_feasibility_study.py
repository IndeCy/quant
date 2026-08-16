"""Quality Balanced Value 叠加五年盈利底线的回测前门禁。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from data.profitability_history import (
    PROFITABILITY_FLOOR_ASOF_TABLE,
    ProfitabilityHistoryPaths,
    attach_profitability_history_databases,
    create_profitability_signal_date_table,
    materialize_profitability_floor_asof,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.quality_profitability_floor_feasibility_report import render_report
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_balanced_value_signal import (
    EXPECTED_WEIGHTS,
    build_quality_balanced_value_topn,
)
from strategies.quality_profitability_floor_signal import (
    apply_positive_profitability_floor,
    build_quality_profitability_floor_topn,
)
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


EXPERIMENT_ID = "quality_profitability_floor_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/quality-profitability-floor-data-feasibility-v1.md"
)
STUDY_START = "20150101"
LOCKED_START = "20220101"
TOP_N = 20
MIN_CONSTRUCTIBLE_SHARE = 0.95
MIN_FLOOR_COVERAGE_MEDIAN = 0.50
MIN_REPLACEMENT_SHARE_MEDIAN = 0.10
MAX_REPLACEMENT_SHARE_MEDIAN = 0.80
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality 盈利底线过滤可行性 V1",
    category="data_feasibility",
    hypothesis="五年最低ROA为正能否作为非破坏性的Quality尾部风险过滤器",
    definition={
        "baseline": {
            "factors": {
                "roe": 0.8 / 3,
                "roa": 0.8 / 3,
                "ocf_to_or": 0.8 / 3,
                "earnings_yield": 0.10,
                "book_yield": 0.10,
            },
            "portfolio": {"top_n": TOP_N, "weight": "equal"},
        },
        "filter": {
            "formula": "min(roa,latest_5_consecutive_annual_reports)>0",
            "role": "eligibility_only_not_alpha_score",
            "visibility": "all_report_publish_dates_lte_signal_date",
            "score_order": "score_full_baseline_cross_section_then_filter",
        },
        "universe": "quality_cleanup_with_corporate_action_gate",
        "frozen_gates": {
            "constructible_share_min": MIN_CONSTRUCTIBLE_SHARE,
            "floor_coverage_median_min": MIN_FLOOR_COVERAGE_MEDIAN,
            "replacement_share_median_range": [
                MIN_REPLACEMENT_SHARE_MEDIAN,
                MAX_REPLACEMENT_SHARE_MEDIAN,
            ],
            "visibility_and_duplicate_violations": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记过滤器语义指纹，再扫描财务历史。"""
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
    """构造基线与过滤后截面，不读取任何未来收益。"""
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
            value for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _quality_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        quality = apply_quality_universe_filters(
            load_annual_quality_candidates(connection)
        )
        quality = attach_report_adjustment_factors(connection, quality)
        baseline, _ = build_quality_value_lowvol_candidates(quality)

        create_profitability_signal_date_table(connection, signal_dates)
        attach_profitability_history_databases(
            connection,
            _profitability_paths(paths),
        )
        materialize_profitability_floor_asof(connection)
        floor = connection.execute(
            f"""
            SELECT signal_date, symbol, latest_publish_date, roa_floor_5y,
                   observations
            FROM {PROFITABILITY_FLOOR_ASOF_TABLE}
            ORDER BY signal_date, symbol
            """
        ).fetchdf()
    finally:
        connection.close()

    merged = baseline.merge(
        floor,
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    filtered = apply_positive_profitability_floor(merged)
    monthly = build_monthly_diagnostics(merged, filtered, signal_dates)
    result = evaluate_feasibility(merged, monthly, latest_date)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def build_monthly_diagnostics(
    baseline: pd.DataFrame,
    filtered: pd.DataFrame,
    signal_dates: list[str],
) -> pd.DataFrame:
    """记录历史覆盖、Top20可构造性和真实替换比例。"""
    _, baseline_holdings = build_quality_balanced_value_topn(
        baseline,
        EXPECTED_WEIGHTS,
        top_n=TOP_N,
    )
    _, filtered_holdings = build_quality_profitability_floor_topn(
        baseline,
        EXPECTED_WEIGHTS,
        top_n=TOP_N,
    )
    rows: list[dict[str, Any]] = []
    for signal_date in signal_dates:
        base = baseline[
            baseline["signal_date"].astype(str).eq(signal_date)
        ]
        accepted = filtered[
            filtered["signal_date"].astype(str).eq(signal_date)
        ]
        base_selected = set(
            baseline_holdings.loc[
                baseline_holdings["signal_date"].astype(str).eq(signal_date),
                "symbol",
            ].astype(str)
        )
        filtered_selected = set(
            filtered_holdings.loc[
                filtered_holdings["signal_date"].astype(str).eq(signal_date),
                "symbol",
            ].astype(str)
        )
        rows.append(
            {
                "signal_date": signal_date,
                "baseline_count": int(len(base)),
                "floor_available_count": int(base["roa_floor_5y"].notna().sum()),
                "filtered_count": int(len(accepted)),
                "constructible": len(accepted) >= TOP_N,
                "floor_coverage": (
                    float(base["roa_floor_5y"].notna().mean())
                    if len(base) else 0.0
                ),
                "replacement_share": (
                    1.0 - len(base_selected & filtered_selected) / TOP_N
                    if len(base_selected) == TOP_N
                    and len(filtered_selected) == TOP_N
                    else 1.0
                ),
            }
        )
    return pd.DataFrame(rows)


def evaluate_feasibility(
    merged: pd.DataFrame,
    monthly: pd.DataFrame,
    latest_date: str,
) -> dict[str, Any]:
    """执行冻结的覆盖、有效过滤和点时门槛。"""
    locked = monthly[monthly["signal_date"].ge(LOCKED_START)]
    constructible = float(monthly["constructible"].mean())
    locked_constructible = float(
        locked["constructible"].mean() if not locked.empty else 0.0
    )
    coverage = float(monthly["floor_coverage"].median())
    replacement = float(monthly["replacement_share"].median())
    visibility = int(
        (
            merged["latest_publish_date"].notna()
            & (
                merged["latest_publish_date"].astype(str)
                > merged["signal_date"].astype(str)
            )
        ).sum()
    )
    duplicate_rows = int(
        merged.duplicated(["signal_date", "symbol"]).sum()
    )
    checks = {
        "full_top20_constructible_share": (
            constructible >= MIN_CONSTRUCTIBLE_SHARE
        ),
        "locked_top20_constructible_share": (
            locked_constructible >= MIN_CONSTRUCTIBLE_SHARE
        ),
        "floor_history_coverage": coverage >= MIN_FLOOR_COVERAGE_MEDIAN,
        "filter_is_not_trivial": (
            replacement + 1e-12 >= MIN_REPLACEMENT_SHARE_MEDIAN
        ),
        "filter_is_not_destructive": replacement <= MAX_REPLACEMENT_SHARE_MEDIAN,
        "zero_visibility_violations": visibility == 0,
        "zero_duplicate_rows": duplicate_rows == 0,
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "floor_coverage_median": coverage,
        "floor_coverage_latest": float(monthly["floor_coverage"].iloc[-1]),
        "filtered_count_min": int(monthly["filtered_count"].min()),
        "filtered_count_median": float(monthly["filtered_count"].median()),
        "filtered_count_latest": int(monthly["filtered_count"].iloc[-1]),
        "constructible_share": constructible,
        "locked_constructible_share": locked_constructible,
        "replacement_share_median": replacement,
        "replacement_share_latest": float(
            monthly["replacement_share"].iloc[-1]
        ),
        "visibility_violations": visibility,
        "duplicate_rows": duplicate_rows,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """保存逐月覆盖和失败也可追踪的可行性结论。"""
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
            "盈利底线覆盖稳定且能非破坏性替换持仓，可执行一次固定回测"
            if passed
            else "盈利底线覆盖或持仓替换门禁未通过，回测前终止"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "逐月覆盖诊断"),
        ],
    )


def _quality_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def _profitability_paths(paths: RuntimePaths) -> ProfitabilityHistoryPaths:
    return ProfitabilityHistoryPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def _data_version(paths: RuntimePaths) -> str:
    parts: list[str] = []
    for label, path in [
        ("indicator", paths.fina_indicator_path),
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
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
