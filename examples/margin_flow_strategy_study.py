"""融资净买入强度策略的固定定义、多阶段可信回测。"""

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
from data.margin_flow import (
    MARGIN_FLOW_ASOF_TABLE,
    create_margin_signal_date_table,
    materialize_margin_flow_asof,
)
from data.margin_trades import attach_margin_trade_database
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples.earnings_forecast_momentum_study import (
    build_annual_metrics,
    load_quality_correlation,
)
from examples.margin_flow_strategy_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.margin_flow import score_margin_flow_frame
from portfolio.topn import select_topn
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


STRATEGY_ID = "margin_financing_flow_v1"
FEASIBILITY_ID = "margin_flow_data_feasibility_v1"
REPORT_PATH = Path("docs/research/margin-financing-flow-v1.md")
FETCH_START = "20141201"
STUDY_START = "20150101"
LOOKBACK_TRADING_DAYS = 20
TOP_N = 20
FOLDS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="融资净买入强度 V1",
    category="factor_strategy",
    hypothesis="持续融资净买入相对成交额是否包含独立、可执行的月频资金行为Alpha",
    definition={
        "dependency": FEASIBILITY_ID,
        "factor": {
            "formula": "sum(rzmre-rzche,20d)/sum(turnover_amount,20d)",
            "lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "positive_only": True,
            "transform": "cross_sectional_percentile_rank",
            "direction": "higher_is_better",
        },
        "visibility": {
            "provider_publish_time": "next_trade_day_0830",
            "signal_T_visible_through": "previous_trade_day",
        },
        "universe": "margin_eligible_listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {
            "top_n": TOP_N,
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
            "annual_turnover_max": 10.0,
            "quality_return_correlation_max": 0.75,
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
    """先登记研究指纹，再读取六百万行两融缓存和行情。"""
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
    """构造 T-1 月度截面并运行统一 M0 回测。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start=FETCH_START,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(
            connection,
            lookback_start=FETCH_START,
            research_start=FETCH_START,
        )
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        attach_margin_trade_database(connection, paths.margin_trade_path)
        create_margin_signal_date_table(connection, signal_dates)
        materialize_margin_flow_asof(
            connection,
            lookback_trading_days=LOOKBACK_TRADING_DAYS,
        )
        candidates = load_margin_flow_candidates(connection)
        targets, holdings, candidate_counts = build_margin_flow_targets(
            signal_dates,
            candidates,
        )
        diagnostics = build_momentum_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("融资净买入强度策略没有产生任何持仓")
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
            candidate_counts,
            diagnostics,
            quality_correlation,
            latest_date,
        ),
        encoding="utf-8",
    )
    return (
        {
            "strategy_id": STRATEGY_ID,
            "latest_date": latest_date,
            "period_metrics": metrics,
            "annual_metrics": annual,
            "quality_return_correlation": quality_correlation,
            "momentum_diagnostics": diagnostics,
            "candidate_counts": candidate_counts,
            "gate": gate,
            "decision": (
                "FORWARD_PAPER_REQUIRED" if gate["passed"] else "REJECTED"
            ),
            "latest_holdings": latest_holdings[
                [
                    "signal_date",
                    "visible_through_date",
                    "symbol",
                    "name",
                    "rank",
                    "factor_score",
                    "margin_flow_intensity",
                    "net_buy_20d",
                    "turnover_20d",
                    "ret20",
                    "ret120",
                ]
            ].to_dict("records"),
            "report_path": str(report_path),
            "reused": False,
        },
        holdings,
        build_nav_frame(run, benchmark),
    )


def load_margin_flow_candidates(connection: Any) -> pd.DataFrame:
    """读取统一点时融资流，并附加仅用于归因的价格动量。"""
    return connection.execute(
        f"""
        SELECT
            m.signal_date,
            m.visible_through_date,
            m.symbol,
            sb.name,
            m.net_buy_20d,
            m.turnover_20d,
            m.margin_flow_intensity,
            f.ret20,
            f.ret120,
            f.vol60
        FROM {MARGIN_FLOW_ASOF_TABLE} m
        JOIN features f
          ON m.signal_date = f.trade_date AND m.symbol = f.symbol
        JOIN stock_basic sb ON m.symbol = sb.ts_code
        ORDER BY m.signal_date, m.symbol
        """
    ).fetchdf()


def build_margin_flow_targets(
    signal_dates: list[str],
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """正融资流生成分数，组合层稳定选择 Top20 等权。"""
    targets: dict[str, dict[str, float]] = {}
    holdings: list[pd.DataFrame] = []
    counts: list[int] = []
    candidate_dates = candidates["signal_date"].astype(str)
    for signal_date in signal_dates:
        group = candidates[candidate_dates.eq(signal_date)]
        scored = score_margin_flow_frame(group)
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
    count_series = pd.Series(counts, dtype=float)
    return targets, combined, {
        "minimum": float(count_series.min()),
        "median": float(count_series.median()),
        "latest": float(count_series.iloc[-1]),
        "months_below_top_n": float(count_series.lt(TOP_N).sum()),
        "empty_months": float(count_series.eq(0).sum()),
    }


def build_momentum_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """诊断融资流是否只是价格动量的别名，不参与选参。"""
    ret20_correlations: list[float] = []
    ret120_correlations: list[float] = []
    top20_overlap: list[float] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        valid = group.dropna(
            subset=["margin_flow_intensity", "ret20", "ret120"]
        ).copy()
        positive = valid[valid["margin_flow_intensity"].gt(0)]
        if len(positive) >= 3:
            ret20_correlations.append(
                float(
                    positive["margin_flow_intensity"].corr(
                        positive["ret20"],
                        method="spearman",
                    )
                )
            )
            ret120_correlations.append(
                float(
                    positive["margin_flow_intensity"].corr(
                        positive["ret120"],
                        method="spearman",
                    )
                )
            )
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        momentum = set(positive.nlargest(TOP_N, "ret120")["symbol"].astype(str))
        if selected and momentum:
            top20_overlap.append(len(selected & momentum) / TOP_N)
    return {
        "median_spearman_ret20": float(pd.Series(ret20_correlations).median()),
        "median_spearman_ret120": float(pd.Series(ret120_correlations).median()),
        "median_top20_overlap_with_momentum": float(
            pd.Series(top20_overlap).median()
        ),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """按研究前冻结门槛判断是否值得前向观察。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    fold_sharpes = pd.Series([item["sharpe"] for item in folds], dtype=float)
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
        "median_fold_sharpe_at_least_035": float(fold_sharpes.median()) >= 0.35,
        "annual_turnover_below_10x": full["annual_turnover"] <= 10.0,
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
    """保存策略、基准和风险仓位每日序列。"""
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
    """把失败与成功的净值、持仓和结论统一资产化。"""
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


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    """收益回测必须显式依赖已通过的数据覆盖门禁。"""
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("融资净买入数据可行性实验尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("融资净买入数据可行性门禁未通过")


def _data_version(paths: RuntimePaths) -> str:
    """绑定两融缓存、行情和基准快照。"""
    parts: list[str] = []
    for label, path in [
        ("margin", paths.margin_trade_path),
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
