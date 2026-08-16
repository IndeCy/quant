"""标准化意外盈利（SUE）的固定事件调仓策略研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from collections.abc import Callable
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
from data.earnings_surprise import (
    EarningsSurprisePaths,
    attach_earnings_surprise_database,
    create_earnings_surprise_signal_date_table,
    materialize_earnings_surprise_asof,
)
from examples.earnings_express_acceleration_study import (
    LOCKED_TEST_START,
    TRAIN_RANGE,
    VALIDATION_RANGE,
    build_annual_metrics,
    evaluate_gate,
    load_quality_correlation,
)
from examples.earnings_surprise_data_feasibility_study import (
    load_earnings_surprise_candidates,
)
from examples.earnings_surprise_strategy_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.earnings_surprise import score_earnings_surprise_frame
from portfolio.topn import select_topn
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "earnings_surprise_event_v1"
REPORT_PATH = Path("docs/research/earnings-surprise-event-v1.md")
STUDY_START = "20150101"
TOP_N = 20
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="标准化意外盈利事件策略 V1",
    category="factor_strategy",
    hypothesis="正向季度EPS意外是否形成独立于Quality的可执行公告后Alpha",
    definition={
        "prerequisite": (
            "earnings_surprise_event_schedule_feasibility_v2_passed"
        ),
        "factor": {
            "formula": (
                "(basic_eps_t-basic_eps_same_quarter_last_year)"
                "/std(prior_8_eps_yoy_changes)"
            ),
            "history_excludes_current": True,
            "gates": [
                "basic_eps_positive",
                "eps_change_positive",
                "event_age_at_most_90_days",
            ],
            "transform": "winsorize_1_99_then_percentile_rank",
        },
        "portfolio": {
            "top_n": TOP_N,
            "weight": "equal",
            "rebalance": "monthly_when_constructible",
            "unconstructible_month": "carry_previous_target",
        },
        "universe": (
            "listed_3y_ex_st_delisted_suspended_bottom20_amount"
        ),
        "risk_overlay": {
            "scheme": "GRID",
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
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "locked_test_annual_return_min": 0.08,
            "locked_test_sharpe_min": 0.55,
            "locked_test_drawdown_floor": -0.30,
            "full_annual_return_min": 0.10,
            "full_sharpe_min": 0.65,
            "full_drawdown_floor": -0.32,
            "annual_turnover_max": 8.0,
            "positive_years_min": 9,
            "quality_return_correlation_max": 0.75,
        },
        "parameters_fixed_before_backtest": True,
        "methodology_version": "sue_event_strategy_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """申请研究指纹后才运行SUE历史回测。"""
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
    """构造公告日点时截面并运行统一M0回测。"""
    result = calculate_strategy(
        paths,
        as_of_date,
        strategy_id=STRATEGY_ID,
        scorer=score_earnings_surprise_frame,
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            result["period_metrics"],
            result["annual_metrics"],
            result["gate"],
            float(result["quality_return_correlation"]),
            result["diagnostics"],
            str(result["latest_date"]),
        ),
        encoding="utf-8",
    )
    return {**result, "report_path": str(report_path)}


def calculate_strategy(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    strategy_id: str,
    scorer: Callable[[pd.DataFrame], pd.DataFrame],
) -> dict[str, Any]:
    """复用同一数据、组合和M0口径计算不同SUE排名版本。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute(
                "SELECT MAX(trade_date) FROM features"
            ).fetchone()[0]
        )
        signal_dates = [
            date
            for date in load_month_end_signal_dates(connection)
            if STUDY_START <= date <= latest_date
        ]
        create_earnings_surprise_signal_date_table(
            connection,
            signal_dates,
        )
        attach_earnings_surprise_database(
            connection,
            EarningsSurprisePaths(paths.income_statement_path),
        )
        materialize_earnings_surprise_asof(connection)
        candidates = load_earnings_surprise_candidates(connection)
        targets, holdings, diagnostics = build_event_targets(
            candidates,
            signal_dates,
            scorer=scorer,
        )
        symbols = sorted(
            holdings["symbol"].astype(str).unique().tolist()
        )
        if not symbols:
            raise ValueError("SUE事件策略没有产生任何历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = [
            date
            for date in load_trading_calendar(connection)
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
    run = run_risk_layer_backtest(
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
    periods = {
        "train": TRAIN_RANGE,
        "validation": VALIDATION_RANGE,
        "locked_test": (LOCKED_TEST_START, latest_date),
        "full": (STUDY_START, latest_date),
    }
    metrics = build_period_metrics(
        {strategy_id: run.result},
        benchmark,
        periods,
    )[strategy_id]
    annual = build_annual_metrics(run, benchmark, latest_date)
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, annual, quality_correlation)
    latest_holdings = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    return {
        "strategy_id": strategy_id,
        "latest_date": latest_date,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "diagnostics": diagnostics,
        "gate": gate,
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "end_date",
                "publish_date",
                "basic_eps",
                "eps_change",
                "historical_change_std",
                "sue",
                "event_age_days",
            ]
        ].to_dict("records"),
        "reused": False,
    }


def build_event_targets(
    candidates: pd.DataFrame,
    signal_dates: list[str],
    *,
    scorer: Callable[
        [pd.DataFrame],
        pd.DataFrame,
    ] = score_earnings_surprise_frame,
) -> tuple[
    dict[str, dict[str, float]],
    pd.DataFrame,
    dict[str, float],
]:
    """候选足够时更新Top20，否则不发新目标并沿用持仓。"""
    targets: dict[str, dict[str, float]] = {}
    holdings: list[pd.DataFrame] = []
    correlations: list[float] = []
    overlaps: list[float] = []
    carried = 0
    for signal_date in signal_dates:
        frame = candidates[
            candidates["signal_date"].astype(str).eq(signal_date)
        ]
        scored = scorer(frame)
        if len(scored) < TOP_N:
            carried += 1
            continue
        selected = select_topn(scored, "factor_score", TOP_N)
        selected["signal_date"] = signal_date
        symbols = selected["symbol"].astype(str).tolist()
        targets[signal_date] = {
            symbol: 1.0 / len(symbols) for symbol in symbols
        }
        holdings.append(selected)
        valid = scored.dropna(subset=["ret120"])
        if len(valid) >= TOP_N:
            correlation = valid["sue"].rank().corr(
                valid["ret120"].rank()
            )
            if pd.notna(correlation):
                correlations.append(float(correlation))
            momentum = set(
                valid.nlargest(TOP_N, "ret120")["symbol"].astype(str)
            )
            overlaps.append(len(set(symbols) & momentum) / TOP_N)
    combined = (
        pd.concat(holdings, ignore_index=True)
        if holdings
        else candidates.iloc[0:0].assign(
            factor_score=pd.Series(dtype=float),
            rank=pd.Series(dtype=int),
        )
    )
    return targets, combined, {
        "rebalance_months": float(len(targets)),
        "carried_months": float(carried),
        "median_spearman_with_ret120": (
            float(pd.Series(correlations).median())
            if correlations
            else float("nan")
        ),
        "median_top20_overlap_with_momentum": (
            float(pd.Series(overlaps).median())
            if overlaps
            else float("nan")
        ),
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """归档报告和最新持仓，失败策略不得注册。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(
        holdings_path,
        index=False,
    )
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED" if passed else "REJECTED",
        decision_reason=(
            "SUE事件策略通过固定门槛，允许进入独立确认"
            if passed
            else "SUE事件策略未通过固定门槛，归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "SUE研究报告"),
            ExperimentArtifact(
                "holdings",
                holdings_path,
                "最新Top20持仓",
            ),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定利润表、行情、基准和Quality观测版本。"""
    files = [
        paths.income_statement_path,
        paths.base_market_path,
        paths.live_market_increment_path,
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        paths.monitoring_path,
    ]
    return "|".join(
        f"{path.name}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for path in files
    )


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
