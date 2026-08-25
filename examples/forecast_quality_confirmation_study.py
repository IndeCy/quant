"""业绩预告与 Quality 等权确认的固定四折回测。"""

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
from data.forecast_events import (
    ForecastEventPaths,
    attach_forecast_database,
    create_forecast_signal_date_table,
    materialize_forecast_event_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.quality_financial import (
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from examples.earnings_express_acceleration_study import build_annual_metrics
from examples.earnings_forecast_momentum_study import (
    LOOKBACK_DAYS,
    load_forecast_candidates,
)
from examples.factor_multifold_revalidation import FOLDS
from examples.forecast_quality_confirmation_report import render_report
from examples.forecast_quality_feasibility_study import (
    EXPERIMENT_ID as FEASIBILITY_ID,
    STUDY_START,
    TOP_N,
    _financial_paths,
    build_combined_candidates,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from factors.earnings_forecast import score_earnings_forecast_frame
from factors.quality import score_quality_frame
from portfolio.topn import build_topn_selections
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
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


STRATEGY_ID = "forecast_quality_confirmation_v1"
FORECAST_CONTROL_ID = "forecast_only_grid_control"
QUALITY_CONTROL_ID = "quality_only_grid_control"
REPORT_PATH = Path("docs/research/forecast-quality-confirmation-v1.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="业绩预告 × Quality 确认 V1",
    category="factor_strategy",
    hypothesis="Quality确认能否降低业绩预告单腿尾部风险并保留其公告Alpha",
    definition={
        "inputs": {
            "forecast": "positive_forecast_90d_asof",
            "quality": ["roe", "roa", "ocf_to_or"],
        },
        "combination": {
            "join": "same_signal_date_and_symbol_inner",
            "transform": "cross_sectional_percentile_rank",
            "weights": {"forecast": 0.5, "quality": 0.5},
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
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
            "full_positive_excess": True,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.30,
            "median_fold_sharpe_min": 0.35,
            "annual_turnover_max": 10.0,
            "forecast_drawdown_improvement_min": 0.10,
            "forecast_sharpe_improvement": True,
            "forecast_annual_return_tolerance": -0.02,
            "parameters_fixed_before_backtest": True,
            "no_follow_up_variants": True,
        },
        "controls": [
            "forecast_only_same_grid",
            "quality_only_same_grid",
        ],
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
    """先登记冻结语义和数据指纹，再执行唯一一次正式回测。"""
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
    """构建候选和两条单腿对照，统一进入 GRID 与 M0。"""
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
        create_forecast_signal_date_table(connection, signal_dates)
        create_quality_signal_date_table(connection, signal_dates)
        attach_forecast_database(connection, ForecastEventPaths(paths.forecast_path))
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_forecast_event_asof(connection, lookback_days=LOOKBACK_DAYS)
        materialize_quality_financial_asof(connection, annual_only=True)
        forecast = load_forecast_candidates(connection)
        quality = apply_quality_universe_filters(
            load_annual_quality_candidates(connection)
        )
        combined = build_combined_candidates(forecast, quality)
        target_sets, holding_sets = build_target_sets(
            combined,
            forecast,
            quality,
        )
        symbols = sorted({
            str(symbol)
            for holdings in holding_sets.values()
            for symbol in holdings["symbol"].tolist()
        })
        if not symbols:
            raise ValueError("确认策略及对照均未产生历史持仓")
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
        strategy_id: _run(strategy_id, targets, bars, calendar, benchmark)
        for strategy_id, targets in target_sets.items()
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
    control_delta = build_control_delta(metrics)
    gate = evaluate_gate(metrics[STRATEGY_ID], control_delta)
    risk_summary = _risk_summary(runs[STRATEGY_ID])
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "control_delta": control_delta,
        "gate": gate,
        "risk_summary": risk_summary,
        "latest_holdings": _latest_records(holding_sets[STRATEGY_ID]),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report_path = Path(result["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    return result, runs, holding_sets[STRATEGY_ID]


def build_target_sets(
    combined: pd.DataFrame,
    forecast: pd.DataFrame,
    quality: pd.DataFrame,
) -> tuple[
    dict[str, dict[str, dict[str, float]]],
    dict[str, pd.DataFrame],
]:
    """从同一原始截面生成候选与两条单腿对照。"""
    combined_scores = combined.copy()
    forecast_scores = _score_by_date(forecast, score_earnings_forecast_frame)
    quality_scores = _score_by_date(quality, score_quality_frame)
    score_sets = {
        STRATEGY_ID: combined_scores,
        FORECAST_CONTROL_ID: forecast_scores,
        QUALITY_CONTROL_ID: quality_scores,
    }
    targets: dict[str, dict[str, dict[str, float]]] = {}
    holdings: dict[str, pd.DataFrame] = {}
    for strategy_id, scores in score_sets.items():
        mapping, selected = build_topn_selections(scores, "factor_score", TOP_N)
        targets[strategy_id] = {
            date: {symbol: 1.0 / len(symbols) for symbol in symbols}
            for date, symbols in mapping.items()
            if symbols
        }
        holdings[strategy_id] = selected
    return targets, holdings


def _score_by_date(frame: pd.DataFrame, scorer: Any) -> pd.DataFrame:
    """按月调用既有单因子评分器，不改变其语义。"""
    frames: list[pd.DataFrame] = []
    for signal_date, group in frame.groupby("signal_date", sort=True):
        scored = scorer(group)
        scored["signal_date"] = str(signal_date)
        if "factor_score" not in scored and "quality_score" in scored:
            scored["factor_score"] = scored["quality_score"]
        frames.append(scored)
    return pd.concat(frames, ignore_index=True)


def _run(
    strategy_id: str,
    targets: dict[str, dict[str, float]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
) -> RiskLayerRun:
    """所有曲线强制复用同一 GRID 风险层与 M0。"""
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


def build_control_delta(
    metrics: dict[str, dict[str, dict[str, float]]],
) -> dict[str, float]:
    """量化确认层相对预告单腿的收益风险变化。"""
    candidate = metrics[STRATEGY_ID]["full"]
    control = metrics[FORECAST_CONTROL_ID]["full"]
    return {
        "drawdown_improvement": (
            candidate["max_drawdown"] - control["max_drawdown"]
        ),
        "sharpe_change": candidate["sharpe"] - control["sharpe"],
        "annual_return_change": (
            candidate["annualized_return"] - control["annualized_return"]
        ),
    }


def evaluate_gate(
    candidate: dict[str, dict[str, float]],
    control_delta: dict[str, float],
) -> dict[str, Any]:
    """执行收益扫描前冻结的绝对门槛和机制门槛。"""
    full = candidate["full"]
    folds = [candidate[key] for key in FOLDS]
    checks = {
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
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
        "annual_turnover_below_10x": full["annual_turnover"] <= 10.0,
        "forecast_drawdown_improves_10pct": (
            control_delta["drawdown_improvement"] >= 0.10
        ),
        "forecast_sharpe_improves": control_delta["sharpe_change"] > 0,
        "forecast_return_loss_within_2pct": (
            control_delta["annual_return_change"] >= -0.02
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_folds": sum(item["annualized_return"] > 0 for item in folds),
        "worst_fold_drawdown": min(item["max_drawdown"] for item in folds),
        "median_fold_sharpe": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        ),
    }


def _risk_summary(run: RiskLayerRun) -> dict[str, float]:
    return {
        "average_exposure": float(run.exposure.mean()),
        "reduced_days": float(run.exposure.lt(1.0).sum()),
        "event_count": float(len(run.events)),
    }


def _latest_records(holdings: pd.DataFrame) -> list[dict[str, Any]]:
    latest = holdings[holdings["signal_date"].eq(holdings["signal_date"].max())]
    columns = [
        "signal_date",
        "symbol",
        "name",
        "rank",
        "factor_score",
        "forecast_score",
        "quality_score",
        "forecast_type",
        "p_change_mid",
        "roe",
        "roa",
        "ocf_to_or",
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
        raise RuntimeError("组合数据可行性实验尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("组合数据可行性门禁未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    holdings: pd.DataFrame,
) -> None:
    """保存三条净值、月度持仓与失败也可追踪的结构化结论。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    nav = {
        strategy_id: (
            run.result.daily_values / float(run.result.daily_values.iloc[0])
        )
        for strategy_id, run in runs.items()
    }
    pd.DataFrame(nav).rename_axis("trade_date").reset_index().to_csv(
        nav_path,
        index=False,
    )
    holdings_path = attempt.output_dir / "monthly_targets.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "确认层通过绝对与单腿改善门槛，仅允许独立前瞻验证"
            if passed
            else "确认层未通过冻结门槛，终止且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "固定四折研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与单腿净值"),
            ExperimentArtifact("monthly_targets", holdings_path, "月度目标组合"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    parts: list[str] = []
    for label, path in [
        ("forecast", paths.forecast_path),
        ("indicator", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
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
