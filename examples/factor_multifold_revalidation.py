"""对仍有样本外生存迹象的独立因子执行统一多折复验。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.forecast_events import ForecastEventPaths
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples import earnings_forecast_momentum_study as forecast
from examples import insider_net_buying_study as insider
from examples.factor_multifold_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "factor_multifold_revalidation_v1"
REPORT_PATH = Path("docs/research/factor-multifold-revalidation-v1.md")
FOLDS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}
FROZEN_CANDIDATES = (
    forecast.STRATEGY_ID,
    insider.STRATEGY_ID,
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="独立因子多折复验 V1",
    category="factor_confirmation",
    hypothesis="锁定期仍有生存迹象的公告事件因子能否跨阶段稳定存在",
    definition={
        "selection": {
            "source": "factor_research_meta_audit_v1",
            "criteria": {
                "original_validation_core_pass": True,
                "locked_annual_return_min": 0.05,
                "locked_sharpe_positive": True,
                "locked_excess_positive": True,
            },
            "candidates": list(FROZEN_CANDIDATES),
            "selection_uses_locked_data": True,
        },
        "strategy_definition": "reuse_original_without_parameter_change",
        "risk_overlay": {
            "scheme": "GRID",
            "window": 20,
            "threshold": 0.45,
            "reduced_exposure": 0.30,
        },
        "folds": FOLDS,
        "gate": {
            "full_annual_return_min": 0.08,
            "full_max_drawdown_floor": -0.30,
            "full_sharpe_min": 0.55,
            "full_positive_excess": True,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.30,
            "median_fold_sharpe_min": 0.35,
            "annual_turnover_max": 10.0,
        },
        "promotion_scope": "retrospective_diagnostic_only",
        "methodology_version": "multifold_v1",
    },
)


@dataclass(frozen=True)
class CandidateBacktest:
    """保存候选完整净值，便于统一切片而不重写指标。"""

    strategy_id: str
    run: RiskLayerRun
    benchmark: pd.Series
    latest_date: str


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记研究身份，再读取行情和事件大表。"""
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
        result, nav_frame = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, nav_frame)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """重跑固定候选，并在四个互不重叠阶段上统一评价。"""
    candidates = [
        _compute_forecast(paths, as_of_date),
        _compute_insider(paths, as_of_date),
    ]
    latest_dates = {item.latest_date for item in candidates}
    if len(latest_dates) != 1:
        raise ValueError(f"候选数据截止日不一致: {sorted(latest_dates)}")
    latest_date = candidates[0].latest_date
    periods = {
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = ("20150101", latest_date)

    metrics: dict[str, dict[str, dict[str, float]]] = {}
    gates: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_metrics = build_period_metrics(
            {candidate.strategy_id: candidate.run.result},
            candidate.benchmark,
            periods,
        )[candidate.strategy_id]
        metrics[candidate.strategy_id] = candidate_metrics
        gates[candidate.strategy_id] = evaluate_gate(candidate_metrics)

    nav_frame = build_nav_frame(candidates)
    correlations = build_return_correlations(nav_frame, periods)
    comparator = load_quality_comparator(paths)
    survivors = [
        strategy_id
        for strategy_id, gate in gates.items()
        if bool(gate["passed"])
    ]
    decision = (
        "RETROSPECTIVE_SURVIVOR_REQUIRES_NEW_FORWARD_PAPER"
        if survivors
        else "REJECT_ALL_CANDIDATES"
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            metrics,
            gates,
            correlations,
            comparator,
            latest_date,
            decision,
        ),
        encoding="utf-8",
    )
    return (
        {
            "latest_date": latest_date,
            "candidate_ids": list(FROZEN_CANDIDATES),
            "period_metrics": metrics,
            "gates": gates,
            "return_correlations": correlations,
            "quality_comparator": comparator,
            "survivors": survivors,
            "decision": decision,
            "promotion_allowed": False,
            "promotion_block_reason": (
                "候选筛选使用了2022年后的锁定数据，已无未观察历史样本"
            ),
            "report_path": str(report_path),
            "reused": False,
        },
        nav_frame,
    )


def _compute_forecast(paths: RuntimePaths, as_of_date: str) -> CandidateBacktest:
    """按原始 V1 定义重建业绩预告候选，不改变任何参数。"""
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
        signal_dates = load_month_end_signal_dates(connection)
        forecast.create_forecast_signal_date_table(connection, signal_dates)
        forecast.attach_forecast_database(
            connection,
            ForecastEventPaths(paths.forecast_path),
        )
        forecast.materialize_forecast_event_asof(
            connection,
            lookback_days=forecast.LOOKBACK_DAYS,
        )
        candidates = forecast.load_forecast_candidates(connection)
        targets, holdings, _ = forecast.build_forecast_targets(candidates)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("业绩预告候选没有历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()
    benchmark = _load_benchmark(paths, latest_date)
    run = _run_candidate(forecast.STRATEGY_ID, targets, bars, calendar, benchmark)
    return CandidateBacktest(forecast.STRATEGY_ID, run, benchmark, latest_date)


def _compute_insider(paths: RuntimePaths, as_of_date: str) -> CandidateBacktest:
    """按原始 V1 定义重建重要股东净增持候选。"""
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
            if insider.STUDY_START <= value <= latest_date
        ]
        insider.create_holder_trade_signal_date_table(connection, signal_dates)
        insider.attach_holder_trade_database(connection, paths.holder_trade_path)
        insider.materialize_holder_trade_asof(
            connection,
            lookback_days=insider.LOOKBACK_DAYS,
        )
        candidates = insider.load_holder_trade_candidates(connection)
        targets, holdings, _ = insider.build_holder_trade_targets(
            candidates,
            signal_dates,
        )
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("重要股东净增持候选没有历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = [
            value
            for value in load_trading_calendar(connection)
            if insider.STUDY_START <= value.strftime("%Y%m%d") <= latest_date
        ]
    finally:
        connection.close()
    benchmark = _load_benchmark(paths, latest_date)
    run = _run_candidate(insider.STRATEGY_ID, targets, bars, calendar, benchmark)
    return CandidateBacktest(insider.STRATEGY_ID, run, benchmark, latest_date)


def _load_benchmark(paths: RuntimePaths, latest_date: str) -> pd.Series:
    """读取与原研究完全一致的 510300 复权曲线。"""
    return load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )


def _run_candidate(
    strategy_id: str,
    targets: dict[str, dict[str, float]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
) -> RiskLayerRun:
    """复用固定风险层和 M0 ExecutionModel。"""
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


def evaluate_gate(metrics: dict[str, dict[str, float]]) -> dict[str, Any]:
    """使用研究前冻结的跨阶段门槛，不根据结果调整。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    checks = {
        "full_annual_return_at_least_8pct": full["annualized_return"] >= 0.08,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_055": full["sharpe"] >= 0.55,
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


def build_nav_frame(candidates: list[CandidateBacktest]) -> pd.DataFrame:
    """保存可重复切片的净值资产，避免以后重跑完整回测。"""
    series: list[pd.Series] = []
    for candidate in candidates:
        values = candidate.run.result.daily_values.astype(float).sort_index()
        series.append((values / float(values.iloc[0])).rename(candidate.strategy_id))
    benchmark = candidates[0].benchmark.astype(float).sort_index()
    series.append((benchmark / float(benchmark.iloc[0])).rename("benchmark_510300"))
    frame = pd.concat(series, axis=1).sort_index()
    frame.index.name = "trade_date"
    return frame.reset_index()


def build_return_correlations(
    nav_frame: pd.DataFrame,
    periods: dict[str, tuple[str, str]],
) -> dict[str, float]:
    """计算两个候选在各阶段的日收益相关性。"""
    frame = nav_frame.set_index(pd.to_datetime(nav_frame["trade_date"]))
    left, right = FROZEN_CANDIDATES
    result: dict[str, float] = {}
    for period, (start, end) in periods.items():
        sliced = frame.loc[pd.Timestamp(start):pd.Timestamp(end), [left, right]]
        result[period] = float(sliced.pct_change().corr().loc[left, right])
    return result


def load_quality_comparator(paths: RuntimePaths) -> dict[str, Any]:
    """从结构化实验仓库读取 Quality 多折确认结果。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        row = connection.execute(
            """
            SELECT metrics_json
            FROM experiment_runs
            WHERE experiment_id = 'quality_balanced_value_forward_paper_v1'
              AND status = 'SUCCESS'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return {}
    metrics = json.loads(str(row[0] or "{}"))
    return {
        "strategy_id": metrics.get("strategy_id"),
        "period_metrics": metrics.get("period_metrics", {}),
        "gate": metrics.get("gate", {}),
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    nav_frame: pd.DataFrame,
) -> None:
    """归档报告、净值和结构化结论，失败候选同样保留。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    nav_frame.to_csv(nav_path, index=False)
    has_survivor = bool(result["survivors"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="RESEARCH_ONLY" if has_survivor else "REJECTED",
        decision_reason=(
            "存在回顾性多折生存者，但必须用全新前瞻Paper验证"
            if has_survivor
            else "两个候选均未通过固定多折门槛，不进入生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "多折复验报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与基准每日净值"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定本轮会读取的全部本地数据文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("forecast", paths.forecast_path),
        ("holder_trade", paths.holder_trade_path),
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
    ]:
        if not path.exists():
            parts.append(f"{label}:missing")
            continue
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
