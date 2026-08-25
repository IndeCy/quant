"""Piotroski 价值策略的固定定义、多阶段可信回测。"""

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
from data.piotroski_financial import (
    PIOTROSKI_ASOF_TABLE,
    PiotroskiFinancialPaths,
    attach_piotroski_financial_databases,
    create_piotroski_signal_date_table,
    materialize_piotroski_financial_asof,
)
from examples.earnings_forecast_momentum_study import (
    build_annual_metrics,
    load_quality_correlation,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from examples.piotroski_value_report import render_report
from factors.piotroski import score_piotroski_value_frame
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


STRATEGY_ID = "piotroski_value_v1"
REPORT_PATH = Path("docs/research/piotroski-value-v1.md")
STUDY_START = "20150101"
TOP_N = 20
HIGH_SCORE_THRESHOLD = 8
VALUE_QUANTILE = 0.20
MIN_MEDIAN_CANDIDATES = 20
MIN_LOCKED_NONEMPTY_SHARE = 0.80
FOLDS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Piotroski 价值策略 V1",
    category="factor_strategy",
    hypothesis="高账面市值比股票中的财务改善能否形成跨阶段、可执行的低频Alpha",
    definition={
        "factor": {
            "primary": "Piotroski_F_Score",
            "threshold": HIGH_SCORE_THRESHOLD,
            "value_pool": {
                "field": "book_equity_div_raw_market_cap",
                "top_quantile": VALUE_QUANTILE,
            },
            "ranking": "f_score_desc_then_book_to_market_desc",
        },
        "financial_visibility": {
            "annual_reports_only": True,
            "f_ann_date_asof_each_statement": True,
            "latest_visible_revision": True,
            "requires_three_consecutive_years": True,
        },
        "universe": "all_a_listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {
            "top_n_max": TOP_N,
            "when_fewer": "hold_all",
            "weight": "equal",
            "rebalance": "monthly",
        },
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
        "folds": FOLDS,
        "frozen_gate": {
            "full_annual_return_min": 0.08,
            "full_drawdown_floor": -0.30,
            "full_sharpe_min": 0.55,
            "full_positive_excess": True,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.30,
            "median_fold_sharpe_min": 0.35,
            "annual_turnover_max": 8.0,
            "quality_return_correlation_max": 0.75,
            "median_candidates_min": MIN_MEDIAN_CANDIDATES,
            "locked_nonempty_share_min": MIN_LOCKED_NONEMPTY_SHARE,
        },
        "parameters_fixed_before_backtest": True,
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记研究指纹后才加载财务与行情大表。"""
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
        result, holdings, nav = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, holdings, nav)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """构建点时价值池、运行 M0，并按固定阶段切片。"""
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
        create_piotroski_signal_date_table(connection, signal_dates)
        attach_piotroski_financial_databases(
            connection,
            PiotroskiFinancialPaths(
                paths.income_statement_path,
                paths.balance_sheet_path,
                paths.cashflow_statement_path,
            ),
        )
        materialize_piotroski_financial_asof(connection)
        candidates = load_piotroski_candidates(connection)
        targets, holdings, coverage = build_piotroski_targets(
            signal_dates,
            candidates,
        )
        if not coverage["passed"]:
            raise ValueError(f"Piotroski portfolio coverage failed: {coverage}")
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
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
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, latest_date)
    metrics = build_period_metrics({STRATEGY_ID: run.result}, benchmark, periods)[
        STRATEGY_ID
    ]
    annual = build_annual_metrics(run, benchmark, latest_date)
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, quality_correlation, coverage)
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
            coverage,
            quality_correlation,
            latest_date,
        ),
        encoding="utf-8",
    )
    nav = build_nav_frame(run, benchmark)
    return (
        {
            "strategy_id": STRATEGY_ID,
            "latest_date": latest_date,
            "period_metrics": metrics,
            "annual_metrics": annual,
            "quality_return_correlation": quality_correlation,
            "candidate_coverage": coverage,
            "gate": gate,
            "decision": (
                "FORWARD_PAPER_REQUIRED" if gate["passed"] else "REJECTED"
            ),
            "latest_holdings": latest_holdings[
                [
                    "signal_date",
                    "symbol",
                    "name",
                    "rank",
                    "f_score",
                    "book_to_market",
                    "report_period",
                    "publish_date",
                ]
            ].to_dict("records"),
            "report_path": str(report_path),
            "reused": False,
        },
        holdings,
        nav,
    )


def load_piotroski_candidates(connection: Any) -> pd.DataFrame:
    """连接标准股票池、原始市值价格与 as-of F-Score。"""
    return connection.execute(
        f"""
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            sb.name,
            p.report_period,
            p.publish_date,
            p.f_score,
            p.book_equity,
            p.total_shares,
            f.raw_close,
            p.book_equity / NULLIF(f.raw_close * p.total_shares, 0)
                AS book_to_market
        FROM features f
        JOIN {PIOTROSKI_ASOF_TABLE} p
          ON f.trade_date = p.signal_date AND f.symbol = p.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        WHERE f.st_name IS NULL
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND f.raw_close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
          AND p.f_score IS NOT NULL
          AND p.book_equity > 0
          AND p.total_shares > 0
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def build_piotroski_targets(
    signal_dates: list[str],
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, Any]]:
    """因子层生成分数，通用 TopN 组合层决定等权目标。"""
    targets: dict[str, dict[str, float]] = {}
    holdings: list[pd.DataFrame] = []
    counts: list[int] = []
    candidate_dates = candidates["signal_date"].astype(str)
    for signal_date in signal_dates:
        group = candidates[candidate_dates.eq(signal_date)]
        scored = score_piotroski_value_frame(
            group,
            high_score_threshold=HIGH_SCORE_THRESHOLD,
            value_quantile=VALUE_QUANTILE,
        )
        counts.append(len(scored))
        selected = select_topn(scored, "factor_score", TOP_N)
        selected["signal_date"] = signal_date
        symbols = selected["symbol"].astype(str).tolist()
        targets[signal_date] = (
            {symbol: 1.0 / len(symbols) for symbol in symbols} if symbols else {}
        )
        if not selected.empty:
            holdings.append(selected)
    combined = (
        pd.concat(holdings, ignore_index=True)
        if holdings
        else candidates.iloc[0:0].copy()
    )
    series = pd.Series(counts, index=signal_dates, dtype=float)
    locked = series[series.index >= "20220101"]
    coverage = {
        "median_candidates": float(series.median()),
        "minimum_candidates": float(series.min()),
        "latest_candidates": float(series.iloc[-1]),
        "empty_months": int(series.eq(0).sum()),
        "locked_nonempty_share": float(locked.gt(0).mean()),
    }
    coverage["passed"] = bool(
        coverage["median_candidates"] >= MIN_MEDIAN_CANDIDATES
        and coverage["locked_nonempty_share"] >= MIN_LOCKED_NONEMPTY_SHARE
    )
    return targets, combined, coverage


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    """按研究前冻结的多阶段门槛验收。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    fold_sharpes = pd.Series([item["sharpe"] for item in folds], dtype=float)
    checks = {
        "portfolio_coverage": bool(coverage["passed"]),
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
        "median_fold_sharpe_at_least_035": float(fold_sharpes.median()) >= 0.35,
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "quality_correlation_at_most_075": (
            pd.notna(quality_correlation) and abs(quality_correlation) <= 0.75
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_folds": sum(item["annualized_return"] > 0 for item in folds),
        "worst_fold_drawdown": min(item["max_drawdown"] for item in folds),
        "median_fold_sharpe": float(fold_sharpes.median()),
    }


def build_nav_frame(run: RiskLayerRun, benchmark: pd.Series) -> pd.DataFrame:
    """保存策略、基准和风险仓位的每日资产序列。"""
    values = run.result.daily_values.astype(float).sort_index()
    benchmark_values = benchmark.astype(float).sort_index()
    frame = pd.concat(
        [
            (values / float(values.iloc[0])).rename("strategy_nav"),
            (benchmark_values / float(benchmark_values.iloc[0])).rename(
                "benchmark_510300_nav"
            ),
            run.exposure.rename("risk_exposure"),
        ],
        axis=1,
    ).sort_index()
    frame.index.name = "trade_date"
    return frame.reset_index()


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    holdings: pd.DataFrame,
    nav: pd.DataFrame,
) -> None:
    """把净值、全部历史持仓和报告登记为研究资产。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    holdings_path = attempt.output_dir / "holdings.csv"
    holdings.to_csv(holdings_path, index=False)
    nav_path = attempt.output_dir / "daily_nav.csv"
    nav.to_csv(nav_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED" if passed else "REJECTED",
        decision_reason=(
            "通过固定多阶段门槛，仅允许进入独立前向 Paper 观察"
            if passed
            else "未通过固定多阶段门槛，归档且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "研究报告"),
            ExperimentArtifact("holdings", holdings_path, "全部历史持仓"),
            ExperimentArtifact("daily_nav", nav_path, "每日净值与风险仓位"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定三张财务表、行情和基准数据版本。"""
    parts: list[str] = []
    for label, path in [
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
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
