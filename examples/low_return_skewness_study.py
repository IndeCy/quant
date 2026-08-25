"""低60日收益偏度因子的固定样本外研究。"""

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
from data.lottery_features import materialize_lottery_max_features
from data.market_features import (
    load_feature_bars,
    load_trading_calendar,
    materialize_market_features,
)
from data.return_skewness import materialize_return_skewness_features
from examples.earnings_express_acceleration_study import (
    LOCKED_TEST_START,
    TRAIN_RANGE,
    VALIDATION_RANGE,
    build_annual_metrics,
    evaluate_gate,
    load_quality_correlation,
)
from examples.low_return_skewness_report import render_report
from examples.low_return_skewness_support import (
    MIN_CANDIDATES,
    MIN_COVERAGE,
    MIN_QUALIFIED_MONTH_SHARE,
    MIN_UNIQUE_VALUES,
    TOP_N,
    build_execution_attribution,
    build_diagnostics,
    build_monthly_coverage,
    build_targets,
    evaluate_data_gate,
    diagnose_execution_attribution,
    load_investable_panel,
    records_without_missing,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "low_return_skewness_60d_v1"
REPORT_PATH = Path("docs/research/low-return-skewness-60d-v1.md")
STUDY_START = "20150101"
WINDOW = 60
RISK_SCHEME = "GRID"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="低60日收益偏度 V1",
    category="factor_strategy",
    hypothesis="规避高正偏彩票型股票是否形成独立且可执行的A股收益溢价",
    definition={
        "factor": {
            "formula": "sample_skewness(qfq_daily_return_trailing_60d)",
            "direction": "lower_is_better",
            "window": WINDOW,
            "transform": "raw_cross_sectional_percentile_rank_no_winsorize",
        },
        "prior_research_distinction": {
            "low_max": "third_moment_not_single_largest_daily_return",
            "low_volatility": "distribution_asymmetry_not_second_moment",
            "momentum": "shape_of_returns_not_cumulative_return",
        },
        "visibility": {
            "signal_uses_data_through_same_day_close": True,
            "minimum_observations": WINDOW,
            "no_future_data": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "data_gate": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "coverage_floor": MIN_COVERAGE,
            "qualified_month_share": MIN_QUALIFIED_MONTH_SHARE,
            "duplicate_signal_symbol_rows": 0,
        },
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
        "risk_overlay": {
            "scheme": RISK_SCHEME,
            "window": 20,
            "threshold": 0.45,
            "reduced_exposure": 0.30,
        },
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "quality_return_correlation_max": 0.75,
            "parameters_fixed_before_backtest": True,
            "no_window_or_topn_search": True,
            "low_max_and_lowvol_are_attribution_only": True,
        },
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先申请冻结研究指纹，再读取日线大表。"""
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
        result, context = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, context)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """先执行覆盖门禁，通过后才运行M0回测。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(
            connection,
            lookback_start="20140701",
            research_start="20140901",
        )
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        materialize_return_skewness_features(connection, window=WINDOW)
        materialize_lottery_max_features(connection, window=20)
        panel = load_investable_panel(connection)
        monthly = build_monthly_coverage(panel)
        data_gate = evaluate_data_gate(panel, monthly)
        if not data_gate["passed"]:
            result = _data_rejection(paths, latest_date, data_gate)
            return result, {"monthly": monthly, "holdings": pd.DataFrame()}
        candidates = panel.dropna(subset=["return_skewness_60d"]).copy()
        targets, holdings, counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("低收益偏度因子没有产生历史持仓")
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
    frictionless_run = run_risk_layer_backtest(
        f"{STRATEGY_ID}_frictionless",
        RISK_SCHEME,
        targets,
        bars,
        calendar,
        benchmark,
        ExecutionModel(
            commission_rate=0.0,
            stamp_tax_rate=0.0,
            slippage_bps=0.0,
            min_commission=0.0,
        ),
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
    metrics = build_period_metrics({STRATEGY_ID: run.result}, benchmark, periods)[
        STRATEGY_ID
    ]
    frictionless_metrics = build_period_metrics(
        {frictionless_run.result.strategy: frictionless_run.result},
        benchmark,
        periods,
    )[frictionless_run.result.strategy]
    execution_attribution = build_execution_attribution(
        metrics,
        frictionless_metrics,
    )
    execution_diagnosis = diagnose_execution_attribution(
        execution_attribution
    )
    annual = build_annual_metrics(run, benchmark, latest_date)
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, annual, quality_correlation)
    latest = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ]
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "decision": "PASSED" if gate["passed"] else "REJECTED",
        "data_gate": data_gate,
        "candidate_counts": counts,
        "period_metrics": metrics,
        "execution_attribution": execution_attribution,
        "execution_diagnosis": execution_diagnosis,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "diagnostics": diagnostics,
        "gate": gate,
        "latest_holdings": records_without_missing(
            latest[
                [
                    "signal_date",
                    "symbol",
                    "name",
                    "rank",
                    "factor_score",
                    "return_skewness_60d",
                    "max_ret20",
                    "vol60",
                    "ret120",
                ]
            ]
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    _write_report(paths, result)
    return result, {"monthly": monthly, "holdings": holdings}


def _data_rejection(
    paths: RuntimePaths,
    latest_date: str,
    data_gate: dict[str, Any],
) -> dict[str, Any]:
    """构造数据门禁失败结果，明确未启动回测。"""
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "decision": "REJECTED_BEFORE_BACKTEST",
        "data_gate": data_gate,
        "latest_holdings": [],
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    _write_report(paths, result)
    return result


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    context: dict[str, pd.DataFrame],
) -> None:
    """归档覆盖、全部持仓和结论，失败同样进入实验仓库。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    holdings_path = attempt.output_dir / "holdings.csv"
    context["monthly"].to_csv(monthly_path, index=False)
    context["holdings"].to_csv(holdings_path, index=False)
    decision = str(result["decision"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "PASSED_RESEARCH_GATE"
            if decision == "PASSED"
            else "REJECTED"
        ),
        decision_reason={
            "PASSED": "低收益偏度通过固定门槛，仅进入独立确认",
            "REJECTED": "低收益偏度未通过回测门槛，终止且不注册",
            "REJECTED_BEFORE_BACKTEST": "偏度数据门禁失败，未启动回测",
        }[decision],
        artifacts=[
            ExperimentArtifact("summary", summary, "低收益偏度报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖"),
            ExperimentArtifact("holdings", holdings_path, "全部月度持仓"),
        ],
    )


def _write_report(paths: RuntimePaths, result: dict[str, Any]) -> None:
    """写入人类可读报告。"""
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情、基准和Quality相关性事实版本。"""
    items = [
        ("base_market", paths.base_market_path),
        ("market_increment", paths.live_market_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
        ("monitoring", paths.monitoring_path),
    ]
    return "|".join(
        f"{label}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for label, path in items
    )


def main() -> None:
    """运行命令行研究入口。"""
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
