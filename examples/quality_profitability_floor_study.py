"""Quality Balanced Value 叠加五年盈利底线的固定多折回测。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.profitability_history import (
    PROFITABILITY_FLOOR_ASOF_TABLE,
    attach_profitability_history_databases,
    create_profitability_signal_date_table,
    materialize_profitability_floor_asof,
)
from data.quality_financial import (
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.earnings_express_acceleration_study import build_annual_metrics
from examples.factor_multifold_revalidation import FOLDS
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_profitability_floor_feasibility_study import (
    EXPERIMENT_ID as FEASIBILITY_ID,
    STUDY_START,
    TOP_N,
    _data_version as _feasibility_data_version,
    _profitability_paths,
    _quality_paths,
)
from examples.quality_profitability_floor_report import render_report
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
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
    build_quality_profitability_floor_topn,
)
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


STRATEGY_ID = "quality_profitability_floor_filter_v1"
BASELINE_ID = "quality_balanced_value_same_run_control"
REPORT_PATH = Path("docs/research/quality-profitability-floor-filter-v1.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality 盈利底线过滤 V1",
    category="factor_strategy",
    hypothesis="五年最低ROA为正能否减少Quality尾部回撤且基本保留收益",
    definition={
        "baseline": {
            "factors": {
                "roe": 0.8 / 3,
                "roa": 0.8 / 3,
                "ocf_to_or": 0.8 / 3,
                "earnings_yield": 0.10,
                "book_yield": 0.10,
            },
            "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
        },
        "filter": {
            "formula": "min(roa,latest_5_consecutive_annual_reports)>0",
            "role": "eligibility_only_not_score",
            "score_order": "score_full_baseline_cross_section_then_filter",
        },
        "risk_overlay": {
            "mode": "GRID",
            "window": 20,
            "threshold": 0.45,
            "reduced_exposure": 0.30,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 5.0,
        },
        "evaluation": {
            "folds": FOLDS,
            "full_annual_return_min": 0.10,
            "full_max_drawdown_floor": -0.30,
            "full_sharpe_min": 0.65,
            "full_calmar_min": 0.40,
            "full_positive_excess": True,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.30,
            "median_fold_sharpe_min": 0.35,
            "annual_turnover_max": 8.0,
            "baseline_full_drawdown_improvement_min": 0.03,
            "baseline_early_drawdown_improvement_min": 0.03,
            "baseline_sharpe_not_worse": True,
            "baseline_annual_return_tolerance": -0.015,
            "parameters_fixed_before_backtest": True,
            "no_follow_up_variants": True,
        },
        "feasibility_dependency": FEASIBILITY_ID,
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记冻结定义后执行候选与原策略同口径对照。"""
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
        _require_feasibility_passed(paths)
        result, runs, holdings = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs, holdings)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun], pd.DataFrame]:
    """重建同一 Quality 截面并只改变盈利底线资格。"""
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
            """
        ).fetchdf()
        merged = baseline.merge(
            floor,
            on=["signal_date", "symbol"],
            how="left",
            validate="one_to_one",
        )
        selections, holding_sets = build_selections(merged)
        symbols = sorted({
            str(symbol)
            for frame in holding_sets.values()
            for symbol in frame["symbol"].tolist()
        })
        bars = load_feature_bars(connection, symbols)
        calendar = [
            date for date in load_trading_calendar(connection)
            if STUDY_START <= date.strftime("%Y%m%d") <= latest_date
        ]
    finally:
        connection.close()

    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    runs = {
        key: _run(key, mapping, bars, calendar, benchmark)
        for key, mapping in selections.items()
    }
    periods = {
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, latest_date)
    metrics = build_period_metrics(
        {key: run.result for key, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(runs[STRATEGY_ID], benchmark, latest_date)
    delta = build_baseline_delta(metrics)
    gate = evaluate_gate(metrics[STRATEGY_ID], delta)
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "baseline_delta": delta,
        "gate": gate,
        "latest_holdings": _latest_records(holding_sets[STRATEGY_ID]),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report_path = Path(result["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    return result, runs, holding_sets[STRATEGY_ID]


def build_selections(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[str]]], dict[str, pd.DataFrame]]:
    """生成原策略和仅加资格过滤的候选策略。"""
    baseline_mapping, baseline_holdings = build_quality_balanced_value_topn(
        candidates,
        EXPECTED_WEIGHTS,
        top_n=TOP_N,
    )
    candidate_mapping, candidate_holdings = (
        build_quality_profitability_floor_topn(
            candidates,
            EXPECTED_WEIGHTS,
            top_n=TOP_N,
        )
    )
    return (
        {
            STRATEGY_ID: candidate_mapping,
            BASELINE_ID: baseline_mapping,
        },
        {
            STRATEGY_ID: candidate_holdings,
            BASELINE_ID: baseline_holdings,
        },
    )


def _run(
    strategy_id: str,
    mapping: dict[str, list[str]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
) -> RiskLayerRun:
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mapping.items()
        if symbols
    }
    return run_risk_layer_backtest(
        strategy_id,
        "GRID",
        targets,
        bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        vol_window=20,
        vol_threshold=0.45,
        reduced_exposure=0.30,
    )


def build_baseline_delta(
    metrics: dict[str, dict[str, dict[str, float]]],
) -> dict[str, float]:
    candidate = metrics[STRATEGY_ID]
    baseline = metrics[BASELINE_ID]
    return {
        "full_drawdown_improvement": (
            candidate["full"]["max_drawdown"]
            - baseline["full"]["max_drawdown"]
        ),
        "early_drawdown_improvement": (
            candidate["2015_2017"]["max_drawdown"]
            - baseline["2015_2017"]["max_drawdown"]
        ),
        "sharpe_change": (
            candidate["full"]["sharpe"] - baseline["full"]["sharpe"]
        ),
        "annual_return_change": (
            candidate["full"]["annualized_return"]
            - baseline["full"]["annualized_return"]
        ),
    }


def evaluate_gate(
    candidate: dict[str, dict[str, float]],
    delta: dict[str, float],
) -> dict[str, Any]:
    """执行回测前冻结的绝对门槛和风险过滤门槛。"""
    full = candidate["full"]
    folds = [candidate[key] for key in FOLDS]
    checks = {
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_calmar_at_least_040": full["calmar"] >= 0.40,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_30pct": (
            min(item["max_drawdown"] for item in folds) >= -0.30
        ),
        "median_fold_sharpe_at_least_035": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.35
        ),
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "full_drawdown_improves_3pct": (
            delta["full_drawdown_improvement"] >= 0.03
        ),
        "early_drawdown_improves_3pct": (
            delta["early_drawdown_improvement"] >= 0.03
        ),
        "baseline_sharpe_not_worse": delta["sharpe_change"] >= 0,
        "baseline_return_loss_within_1_5pct": (
            delta["annual_return_change"] >= -0.015
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _latest_records(holdings: pd.DataFrame) -> list[dict[str, Any]]:
    latest = holdings[holdings["signal_date"].eq(holdings["signal_date"].max())]
    columns = [
        "signal_date",
        "symbol",
        "name",
        "rank",
        "factor_score",
        "roa_floor_5y",
        "roe",
        "roa",
        "ocf_to_or",
        "earnings_yield",
        "book_yield",
    ]
    return [
        {key: None if pd.isna(value) else value for key, value in row.items()}
        for row in latest[columns].to_dict("records")
    ]


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("Quality盈利底线可行性实验尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("Quality盈利底线可行性门禁未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    holdings: pd.DataFrame,
) -> None:
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame({
        key: run.result.daily_values / float(run.result.daily_values.iloc[0])
        for key, run in runs.items()
    }).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "monthly_targets.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "盈利底线过滤通过绝对与风险改善门槛，仅进入前瞻验证"
            if passed
            else "盈利底线过滤未实质改善回撤，终止且不注册生产"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "固定多折研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与基线净值"),
            ExperimentArtifact("monthly_targets", holdings_path, "月度目标组合"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    base = _feasibility_data_version(paths)
    for label, path in [
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
    ]:
        stat = path.stat()
        base += f"|{label}:{stat.st_size}:{stat.st_mtime_ns}"
    return base


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
