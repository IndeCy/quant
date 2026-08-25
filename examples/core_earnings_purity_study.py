"""核心利润纯度单因子的点时多折研究。"""

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
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from examples.core_earnings_purity_report import render_report
from examples.core_earnings_purity_support import (
    TOP_N,
    build_candidates,
    build_diagnostics,
    build_monthly_coverage,
    build_targets,
    evaluate_data_gate,
    records_without_missing,
)
from examples.earnings_express_acceleration_study import (
    build_annual_metrics,
    load_quality_correlation,
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
from strategies.quality_universe import load_annual_quality_candidates


STRATEGY_ID = "core_earnings_purity_v1"
REPORT_PATH = Path("docs/research/core-earnings-purity-v1.md")
STUDY_START = "20150101"
RISK_SCHEME = "GRID"
FOLDS = {
    "fold_2015_2017": ("20150101", "20171231"),
    "fold_2018_2020": ("20180101", "20201231"),
    "fold_2021_2023": ("20210101", "20231231"),
    "locked_2024_latest": ("20240101", "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="核心利润纯度 V1",
    category="factor_strategy",
    hypothesis="盈利公司主营扣非利润占比越高是否形成稳定且独立的收益溢价",
    definition={
        "factor": {
            "source_field": "dtprofit_to_profit",
            "meaning": "deducted_non_recurring_profit_to_net_profit",
            "direction": "higher_is_better",
            "eligibility": "roa_positive",
            "transform": "monthly_winsorize_1_99_then_percentile_rank",
        },
        "visibility": {
            "annual_1231_only": True,
            "publish_date": "conservative_max_statement_f_ann_date",
            "publish_date_lte_signal_date": True,
            "report_freshness_years": [1, 2],
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {
            "top_n": TOP_N,
            "weight": "equal",
            "rebalance": "monthly",
        },
        "risk_overlay": {
            "scheme": RISK_SCHEME,
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
            "full_period": [STUDY_START, "LATEST"],
            "parameters_fixed_before_backtest": True,
            "no_parameter_search": True,
            "quality_return_correlation_max": 0.75,
        },
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先申请冻结指纹，再读取财务和行情大表。"""
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
    """先执行数据门禁，通过后才启动M0多折回测。"""
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
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(
            connection,
            _financial_paths(paths),
        )
        materialize_quality_financial_asof(connection, annual_only=True)
        source = load_annual_quality_candidates(connection)
        candidates, source_diagnostics = build_candidates(source)
        monthly = build_monthly_coverage(candidates, signal_dates)
        data_gate = evaluate_data_gate(monthly, source_diagnostics)
        if not data_gate["passed"]:
            result = _data_rejection(paths, latest_date, data_gate)
            return result, {
                "monthly": monthly,
                "holdings": pd.DataFrame(),
                "daily_nav": pd.DataFrame(),
            }
        targets, holdings = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("核心利润纯度没有产生历史持仓")
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
    periods = {
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, latest_date)
    metrics = build_period_metrics(
        {STRATEGY_ID: run.result},
        benchmark,
        periods,
    )[STRATEGY_ID]
    annual = build_annual_metrics(run, benchmark, latest_date)
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_multifold_gate(metrics, quality_correlation)
    latest = holdings[
        holdings["signal_date"].astype(str).eq(
            str(holdings["signal_date"].max())
        )
    ]
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "decision": "PASSED" if gate["passed"] else "REJECTED",
        "data_gate": data_gate,
        "period_metrics": metrics,
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
                    "dtprofit_to_profit",
                    "roa",
                    "ocf_to_or",
                    "salescash_to_or",
                ]
            ]
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    _write_report(paths, result)
    nav = run.result.daily_values.rename("portfolio_value").reset_index()
    nav.columns = ["trade_date", "portfolio_value"]
    return result, {
        "monthly": monthly,
        "holdings": holdings,
        "daily_nav": nav,
    }


def evaluate_multifold_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """使用研究前冻结的跨阶段、风险、成本和独立性门槛。"""
    historical = [
        metrics["fold_2015_2017"],
        metrics["fold_2018_2020"],
        metrics["fold_2021_2023"],
    ]
    all_folds = [*historical, metrics["locked_2024_latest"]]
    locked = metrics["locked_2024_latest"]
    full = metrics["full"]
    positive_historical = sum(
        item["annualized_return"] > 0 for item in historical
    )
    median_fold_sharpe = float(
        pd.Series([item["sharpe"] for item in all_folds]).median()
    )
    worst_fold_drawdown = min(
        item["max_drawdown"] for item in all_folds
    )
    checks = {
        "locked_annual_return_at_least_5pct": (
            locked["annualized_return"] >= 0.05
        ),
        "locked_sharpe_positive": locked["sharpe"] > 0,
        "locked_drawdown_within_30pct": (
            locked["max_drawdown"] >= -0.30
        ),
        "locked_positive_excess": locked["excess_return"] > 0,
        "full_annual_return_at_least_8pct": (
            full["annualized_return"] >= 0.08
        ),
        "full_sharpe_at_least_055": full["sharpe"] >= 0.55,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_two_positive_historical_folds": (
            positive_historical >= 2
        ),
        "worst_fold_drawdown_within_30pct": (
            worst_fold_drawdown >= -0.30
        ),
        "median_fold_sharpe_at_least_035": (
            median_fold_sharpe >= 0.35
        ),
        "annual_turnover_below_10x": (
            full["annual_turnover"] <= 10.0
        ),
        "quality_correlation_at_most_075": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.75
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_historical_folds": positive_historical,
        "median_fold_sharpe": median_fold_sharpe,
        "worst_fold_drawdown": worst_fold_drawdown,
    }


def _data_rejection(
    paths: RuntimePaths,
    latest_date: str,
    data_gate: dict[str, Any],
) -> dict[str, Any]:
    """构造数据门禁失败结果，不伪造回测输出。"""
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
    """归档报告、覆盖、持仓和净值，失败结论同样进入实验库。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    holdings_path = attempt.output_dir / "holdings.csv"
    nav_path = attempt.output_dir / "daily_nav.csv"
    context["monthly"].to_csv(monthly_path, index=False)
    context["holdings"].to_csv(holdings_path, index=False)
    context["daily_nav"].to_csv(nav_path, index=False)
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
            "PASSED": "核心利润纯度通过多折门槛，仅进入独立确认",
            "REJECTED": "核心利润纯度未通过多折门槛，终止且不注册",
            "REJECTED_BEFORE_BACKTEST": "核心利润纯度数据门禁失败",
        }[decision],
        artifacts=[
            ExperimentArtifact("summary", summary, "核心利润纯度报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖"),
            ExperimentArtifact("holdings", holdings_path, "全部历史持仓"),
            ExperimentArtifact("daily_nav", nav_path, "每日净值"),
        ],
    )


def _write_report(paths: RuntimePaths, result: dict[str, Any]) -> None:
    """写入人类可读报告。"""
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    """返回统一财务库路径。"""
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情、财务、基准和Quality对照数据版本。"""
    items = [
        ("base_market", paths.base_market_path),
        ("market_increment", paths.live_market_increment_path),
        ("indicator", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
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
