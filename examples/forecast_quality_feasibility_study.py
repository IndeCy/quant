"""业绩预告与 Quality 等权确认组合的回测前数据门禁。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.forecast_events import (
    ForecastEventPaths,
    attach_forecast_database,
    create_forecast_signal_date_table,
    materialize_forecast_event_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from examples.earnings_forecast_momentum_study import (
    LOOKBACK_DAYS,
    load_forecast_candidates,
)
from examples.forecast_quality_feasibility_report import render_report
from factors.earnings_forecast import score_earnings_forecast_frame
from factors.forecast_quality_confirmation import (
    score_forecast_quality_confirmation,
)
from factors.quality import score_quality_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


EXPERIMENT_ID = "forecast_quality_confirmation_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/forecast-quality-confirmation-data-feasibility-v1.md"
)
STUDY_START = "20150101"
LOCKED_START = "20220101"
TOP_N = 40
MIN_CONSTRUCTIBLE_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MAX_INPUT_CORRELATION = 0.80
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="业绩预告 × Quality 确认可行性 V1",
    category="data_feasibility",
    hypothesis="正向业绩预告与当前财务质量的等权确认能否形成稳定可交易截面",
    definition={
        "inputs": {
            "forecast": {
                "source": "forecast_ann_date_asof",
                "lookback_days": LOOKBACK_DAYS,
                "types": ["预增", "略增", "续盈"],
                "positive_bounds_only": True,
            },
            "quality": {
                "factors": ["roe", "roa", "ocf_to_or"],
                "source": "annual_f_ann_date_asof",
            },
        },
        "combination": {
            "join": "same_signal_date_and_symbol_inner",
            "transform": "cross_sectional_percentile_rank",
            "weights": {"forecast": 0.5, "quality": 0.5},
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "candidate_portfolio": {"top_n": TOP_N, "weight": "equal"},
        "frozen_gates": {
            "full_top40_constructible_share": MIN_CONSTRUCTIBLE_SHARE,
            "locked_top40_constructible_share": MIN_CONSTRUCTIBLE_SHARE,
            "top40_median_adv_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "input_rank_correlation_max": MAX_INPUT_CORRELATION,
            "duplicate_visibility_invalid_violations": 0,
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
    """先登记组合语义指纹，再扫描两个点时来源。"""
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
    """构造双来源交集并执行冻结门禁。"""
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
        create_forecast_signal_date_table(connection, signal_dates)
        create_quality_signal_date_table(connection, signal_dates)
        attach_forecast_database(
            connection,
            ForecastEventPaths(paths.forecast_path),
        )
        attach_quality_financial_databases(
            connection,
            _financial_paths(paths),
        )
        materialize_forecast_event_asof(
            connection,
            lookback_days=LOOKBACK_DAYS,
        )
        materialize_quality_financial_asof(connection, annual_only=True)
        forecast = load_forecast_candidates(connection)
        quality = apply_quality_universe_filters(
            load_annual_quality_candidates(connection)
        )
    finally:
        connection.close()

    candidates = build_combined_candidates(forecast, quality)
    monthly = build_monthly_coverage(candidates, signal_dates)
    result = evaluate_feasibility(candidates, monthly, latest_date)
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def build_combined_candidates(
    forecast: pd.DataFrame,
    quality: pd.DataFrame,
) -> pd.DataFrame:
    """逐月评分后只保留同月同票具备两类信号的记录。"""
    forecast_frames: list[pd.DataFrame] = []
    for signal_date, group in forecast.groupby("signal_date", sort=True):
        scored = score_earnings_forecast_frame(group).rename(
            columns={"factor_score": "forecast_score"}
        )
        scored["signal_date"] = str(signal_date)
        forecast_frames.append(scored)
    quality_frames: list[pd.DataFrame] = []
    for signal_date, group in quality.groupby("signal_date", sort=True):
        scored = score_quality_frame(group)
        scored["signal_date"] = str(signal_date)
        quality_frames.append(scored)
    if not forecast_frames or not quality_frames:
        return pd.DataFrame()
    forecast_scores = pd.concat(forecast_frames, ignore_index=True)
    quality_scores = pd.concat(quality_frames, ignore_index=True)
    quality_columns = [
        "signal_date",
        "symbol",
        "quality_score",
        "roe",
        "roa",
        "ocf_to_or",
        "amount20",
        "f_ann_date",
    ]
    merged = forecast_scores.merge(
        quality_scores[quality_columns],
        on=["signal_date", "symbol"],
        how="inner",
        validate="one_to_one",
    )
    frames: list[pd.DataFrame] = []
    for signal_date, group in merged.groupby("signal_date", sort=True):
        scored = score_forecast_quality_confirmation(group)
        scored["signal_date"] = str(signal_date)
        scored["adv_rmb"] = (
            pd.to_numeric(scored["amount20"], errors="coerce") * 1000.0
        )
        frames.append(scored)
    return pd.concat(frames, ignore_index=True) if frames else merged.iloc[0:0]


def build_monthly_coverage(
    candidates: pd.DataFrame,
    signal_dates: list[str],
) -> pd.DataFrame:
    """保留空月并记录构造能力、输入相关性与成交额。"""
    rows: list[dict[str, Any]] = []
    for signal_date in signal_dates:
        if candidates.empty:
            group = candidates
            selected = candidates
            correlation = np.nan
        else:
            group = candidates[
                candidates["signal_date"].astype(str).eq(signal_date)
            ]
            selected = group.nlargest(TOP_N, "factor_score")
            correlation = group["forecast_score"].corr(
                group["quality_score"],
                method="spearman",
            )
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(len(group)),
                "unique_score_count": int(group["factor_score"].nunique()),
                "top40_constructible": len(group) >= TOP_N,
                "top40_median_adv_rmb": (
                    float(selected["adv_rmb"].median())
                    if len(selected)
                    else 0.0
                ),
                "forecast_quality_spearman": (
                    float(correlation) if pd.notna(correlation) else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def evaluate_feasibility(
    candidates: pd.DataFrame,
    monthly: pd.DataFrame,
    latest_date: str,
) -> dict[str, Any]:
    """按预先冻结的覆盖、独立性和点时门槛判断。"""
    if monthly.empty:
        raise ValueError("没有可审计的月末信号日")
    locked = monthly[monthly["signal_date"].ge(LOCKED_START)]
    constructible = float(monthly["top40_constructible"].mean())
    locked_constructible = float(
        locked["top40_constructible"].mean() if not locked.empty else 0.0
    )
    duplicate_rows = int(
        candidates.duplicated(["signal_date", "symbol"]).sum()
    )
    visibility = int(
        (
            candidates["publish_date"].astype(str)
            > candidates["signal_date"].astype(str)
        ).sum()
        + (
            candidates["f_ann_date"].astype(str)
            > candidates["signal_date"].astype(str)
        ).sum()
    )
    invalid = int(
        (
            ~np.isfinite(
                pd.to_numeric(candidates["factor_score"], errors="coerce")
            )
        ).sum()
    )
    correlation = float(monthly["forecast_quality_spearman"].median())
    adv = float(monthly["top40_median_adv_rmb"].median())
    checks = {
        "full_top40_constructible_share": (
            constructible >= MIN_CONSTRUCTIBLE_SHARE
        ),
        "locked_top40_constructible_share": (
            locked_constructible >= MIN_CONSTRUCTIBLE_SHARE
        ),
        "top40_liquidity": adv >= MIN_TOP40_MEDIAN_ADV_RMB,
        "inputs_not_redundant": abs(correlation) <= MAX_INPUT_CORRELATION,
        "zero_visibility_violations": visibility == 0,
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_invalid_scores": invalid == 0,
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "top40_constructible_share": constructible,
        "locked_top40_constructible_share": locked_constructible,
        "unique_score_median": float(
            monthly["unique_score_count"].median()
        ),
        "top40_adv_median_rmb": adv,
        "forecast_quality_correlation_median": correlation,
        "visibility_violations": visibility,
        "duplicate_rows": duplicate_rows,
        "invalid_rows": invalid,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """保存交集门禁与逐月覆盖，失败也进入实验历史。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if result["passed"] else "REJECTED",
        decision_reason=(
            "预告与Quality交集覆盖稳定，可执行一次固定四折回测"
            if result["passed"]
            else "预告与Quality交集覆盖、点时或流动性门禁未通过"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "组合数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "逐月交集覆盖"),
        ],
    )


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定预告、财务、行情与增量数据版本。"""
    parts: list[str] = []
    for label, path in [
        ("forecast", paths.forecast_path),
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
