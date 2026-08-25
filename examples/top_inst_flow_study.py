"""机构席位近20日净买入强度的固定四折回测。"""

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
from data.top_inst import (
    TushareTopInstClient,
    attach_top_inst_database,
    create_top_inst_signal_dates,
    materialize_top_inst_flow_asof,
    update_top_inst_cache,
)
from examples.earnings_express_acceleration_study import (
    build_annual_metrics,
    load_quality_correlation,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from examples.top_inst_flow_report import render_report
from examples.top_inst_flow_study_support import (
    FOLDS,
    TOP_N,
    build_diagnostics,
    build_targets,
    evaluate_gate,
    load_backtest_panel,
)
from runtime.config import get_config_value
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


STRATEGY_ID = "top_inst_flow_20d_v1_1"
REPORT_PATH = Path("docs/research/top-inst-flow-20d-v1-1.md")
FEASIBILITY_ID = "top_inst_flow_data_feasibility_v1"
STUDY_START = "20170101"
FETCH_START = "20161201"
LOOKBACK_TRADING_DAYS = 20
RISK_SCHEME = "GRID"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="机构席位净买入强度 V1.1",
    category="factor_strategy",
    hypothesis="去重后的机构席位正净买入强度能否形成跨阶段可执行Alpha",
    definition={
        "factor": {
            "formula": "deduplicated_20d_net_buy/amount20_rmb",
            "direction": "higher_is_better",
            "lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "eligible": "positive_net_buy_only",
            "transform": "raw_cross_sectional_percentile_rank",
            "deduplication": (
                "trade_date_ts_code_exalter_buy_sell_net_buy_ignore_side_reason"
            ),
        },
        "visibility": {
            "event_date_lte_signal_date": True,
            "month_end_close_signal_next_trading_day_execution": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {
            "top_n": TOP_N,
            "weight": "equal",
            "rebalance": "monthly",
            "insufficient_candidates": "cash",
        },
        "risk_overlay": {
            "implementation_scheme": RISK_SCHEME,
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
            "full_annual_return_min": 0.08,
            "full_max_drawdown_floor": -0.30,
            "full_sharpe_min": 0.55,
            "full_positive_excess": True,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.30,
            "median_fold_sharpe_min": 0.35,
            "annual_turnover_max": 10.0,
            "quality_return_correlation_max": 0.75,
            "parameters_fixed_before_backtest": True,
            "no_follow_up_variants": True,
        },
        "feasibility_dependency": FEASIBILITY_ID,
        "supersedes": {
            "experiment_id": "top_inst_flow_20d_v1",
            "reason": "v1误用FIXED满仓基线，未执行预注册波动率风险层",
        },
        "methodology_version": "multifold_v1_1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    request_interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """登记冻结指纹后，执行唯一一次完整历史回测。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(paths, as_of_date),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date, request_interval_seconds)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
    request_interval_seconds: float,
) -> dict[str, Any]:
    """回补完整历史，构造目标组合并复用固定风险层与 M0。"""
    _require_feasibility_passed(paths)
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
        trade_dates = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT trade_date
                FROM features
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                [FETCH_START, signal_dates[-1]],
            ).fetchall()
        ]
    finally:
        connection.close()

    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
    cache_path = paths.data_dir / "top_inst_increment.duckdb"
    sync = update_top_inst_cache(
        TushareTopInstClient(token),
        cache_path,
        trade_dates,
        request_interval_seconds=request_interval_seconds,
        progress_callback=_progress,
    )
    if not sync.success:
        preview = ",".join(sync.failed_dates[:5])
        raise RuntimeError(f"机构席位完整历史同步失败，待续跑日期: {preview}")

    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        create_top_inst_signal_dates(connection, signal_dates)
        attach_top_inst_database(connection, cache_path)
        materialize_top_inst_flow_asof(
            connection,
            lookback_trading_days=LOOKBACK_TRADING_DAYS,
        )
        candidates = load_backtest_panel(connection)
        targets, holdings, candidate_counts = build_targets(
            candidates,
            signal_dates,
        )
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("机构席位净买入没有产生历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = [
            value
            for value in load_trading_calendar(connection)
            if STUDY_START <= value.strftime("%Y%m%d") <= latest_date
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
        STRATEGY_ID,
        RISK_SCHEME,
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
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, latest_date)
    metrics = build_period_metrics({STRATEGY_ID: run.result}, benchmark, periods)[
        STRATEGY_ID
    ]
    annual_all = build_annual_metrics(run, benchmark, latest_date)
    annual = {
        year: item for year, item in annual_all.items() if year >= STUDY_START[:4]
    }
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, quality_correlation)
    latest_holdings = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            metrics,
            annual,
            gate,
            quality_correlation,
            diagnostics,
            candidate_counts,
            latest_date,
        ),
        encoding="utf-8",
    )
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "gate": gate,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "diagnostics": diagnostics,
        "candidate_counts": candidate_counts,
        "sync": sync.__dict__,
        "latest_holdings": _records_without_missing(
            latest_holdings[
                [
                    "signal_date",
                    "symbol",
                    "name",
                    "rank",
                    "factor_score",
                    "net_buy_to_adv",
                    "total_net_buy",
                    "event_days",
                    "unique_seat_events",
                    "adv_rmb",
                    "vol60",
                    "ret120",
                ]
            ]
        ),
        "report_path": str(report_path),
        "reused": False,
    }


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    """只信任实验仓库中的成功门禁，不读取Markdown推断状态。"""
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("机构席位数据可行性实验尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("机构席位数据可行性门禁未通过")


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档报告和最新持仓，未通过策略同样保留。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED" if passed else "REJECTED",
        decision_reason=(
            "机构席位净买入通过固定四折门槛，允许进入独立确认"
            if passed
            else "机构席位净买入未通过固定四折门槛，终止且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "机构席位研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新Top20持仓"),
        ],
    )


def _records_without_missing(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {key: None if pd.isna(value) else value for key, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _progress(current: int, total: int, trade_date: str) -> None:
    if current == 1 or current == total or current % 100 == 0:
        print(f"top_inst full sync {current}/{total}: {trade_date}", flush=True)


def _data_version(paths: RuntimePaths, as_of_date: str) -> str:
    """绑定行情、基准和完整远端接口契约。"""
    parts = [f"tushare_top_inst_daily:{FETCH_START}:{as_of_date}"]
    for label, path in [
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
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--request-interval", type=float, default=0.0)
    args = parser.parse_args()
    print(
        run_study(
            get_runtime_paths(),
            args.as_of_date,
            force=args.force,
            request_interval_seconds=args.request_interval,
        )
    )


if __name__ == "__main__":
    main()
