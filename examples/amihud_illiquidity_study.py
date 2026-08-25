"""Amihud 非流动性溢价的固定四折回测。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.amihud_illiquidity import materialize_amihud_illiquidity
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples.amihud_illiquidity_feasibility_study import (
    STUDY_START,
    WINDOW,
    load_investable_panel,
)
from examples.amihud_illiquidity_report import render_report
from examples.earnings_express_acceleration_study import (
    build_annual_metrics,
    load_quality_correlation,
)
from examples.factor_multifold_revalidation import FOLDS
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.amihud_illiquidity import score_amihud_illiquidity_frame
from portfolio.topn import build_topn_selections
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "amihud_illiquidity_60d_v1"
REPORT_PATH = Path("docs/research/amihud-illiquidity-60d-v1.md")
TOP_N = 40
REFERENCE_CAPITAL = 5_000_000.0
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Amihud非流动性溢价 V1",
    category="factor_strategy",
    hypothesis="可交易范围内的单位成交额价格冲击能否形成跨阶段独立Alpha",
    definition={
        "factor": {
            "formula": "mean(abs(qfq_daily_return)/(amount*1000),60d)",
            "direction": "higher_is_better",
            "amount_source_unit": "tushare_thousand_cny",
            "amount_normalized_unit": "cny",
            "transform": "raw_cross_sectional_percentile_rank",
        },
        "prior_research_distinction": {
            "quality_liquidity_extension_v1": (
                "illiquidity_premium_not_high_liquidity_quality_tilt"
            ),
            "abnormal_volume": "price_impact_level_not_self_relative_volume_shock",
            "signed_amount_pressure": "absolute_impact_not_signed_short_momentum",
        },
        "visibility": {
            "window": WINDOW,
            "same_day_close_signal_next_trading_day_execution": True,
            "no_future_data": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
        "tradability": {
            "reference_capital": REFERENCE_CAPITAL,
            "feasibility_dependency": "amihud_illiquidity_data_feasibility_v1",
        },
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
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
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记冻结研究指纹，再读取日线和执行回测。"""
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
    """构造非流动性目标，并复用固定风险层与 M0。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        materialize_amihud_illiquidity(connection, window=WINDOW)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        candidates = load_investable_panel(connection, signal_dates)
        targets, holdings, candidate_counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("Amihud非流动性没有产生历史持仓")
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
        "latest_holdings": records_without_missing(
            latest_holdings[
                [
                    "signal_date",
                    "symbol",
                    "name",
                    "rank",
                    "factor_score",
                    "amihud_illiquidity",
                    "average_amount_rmb",
                    "amount20_rmb",
                    "maximum_daily_impact_share",
                    "vol60",
                    "ret120",
                ]
            ]
        ),
        "report_path": str(report_path),
        "reused": False,
    }


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """逐月选择 Amihud 最高的 Top40 并等权。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_amihud_illiquidity_frame(group)
        scored["signal_date"] = str(signal_date)
        counts[str(signal_date)] = len(scored)
        if len(scored) >= TOP_N:
            frames.append(scored)
    if not frames:
        empty = candidates.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
        return {}, empty, {"min": 0.0, "median": 0.0, "latest": 0.0}
    scores = pd.concat(frames, ignore_index=True)
    mappings, holdings = build_topn_selections(scores, "factor_score", TOP_N)
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mappings.items()
    }
    values = pd.Series(counts, dtype=float)
    return targets, holdings, {
        "min": float(values.min()),
        "median": float(values.median()),
        "latest": float(values.iloc[-1]),
    }


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """归因成交额、价格波动、动量与实际参与率。"""
    correlations: dict[str, list[float]] = {
        "amount20_rmb": [],
        "vol60": [],
        "ret120": [],
    }
    overlaps: dict[str, list[float]] = {
        "low_amount": [],
        "high_vol60": [],
        "ret120": [],
    }
    cutoff_ties: list[int] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_amihud_illiquidity_frame(group)
        if len(scored) < TOP_N:
            continue
        rank = scored["factor_score"].rank()
        for field in correlations:
            value = rank.corr(scored[field].rank())
            if pd.notna(value):
                correlations[field].append(float(value))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        comparators = {
            "low_amount": scored.nsmallest(TOP_N, "amount20_rmb"),
            "high_vol60": scored.nlargest(TOP_N, "vol60"),
            "ret120": scored.nlargest(TOP_N, "ret120"),
        }
        for key, comparator in comparators.items():
            symbols = set(comparator["symbol"].astype(str))
            overlaps[key].append(len(selected & symbols) / TOP_N)
        cutoff = scored["factor_score"].nlargest(TOP_N).iloc[-1]
        cutoff_ties.append(int(scored["factor_score"].eq(cutoff).sum()))
    selected_adv = pd.to_numeric(holdings["amount20_rmb"], errors="coerce")
    median_adv = float(selected_adv.median())
    return {
        "median_spearman_with_amount20": _median(
            correlations["amount20_rmb"]
        ),
        "median_spearman_with_vol60": _median(correlations["vol60"]),
        "median_spearman_with_ret120": _median(correlations["ret120"]),
        "median_top40_overlap_with_low_amount": _median(
            overlaps["low_amount"]
        ),
        "median_top40_overlap_with_high_vol60": _median(
            overlaps["high_vol60"]
        ),
        "median_top40_overlap_with_ret120": _median(overlaps["ret120"]),
        "selected_adv_median_rmb": median_adv,
        "selected_adv_p01_rmb": float(selected_adv.quantile(0.01)),
        "reference_capital_participation": (
            REFERENCE_CAPITAL / TOP_N / median_adv
        ),
        "selected_impact_concentration_median": float(
            holdings["maximum_daily_impact_share"].median()
        ),
        "maximum_cutoff_tie_count": float(max(cutoff_ties)),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """执行冻结的跨阶段、风险、成本和独立性门槛。"""
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
        "quality_correlation_at_most_075": (
            pd.notna(quality_correlation) and abs(quality_correlation) <= 0.75
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


def records_without_missing(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """把研究产物缺失值转换成 JSON null。"""
    return [
        {key: None if pd.isna(value) else value for key, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档报告和持仓，失败策略同样保留确定性指纹。"""
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
            "Amihud非流动性通过固定四折门槛，允许进入独立确认"
            if passed
            else "Amihud非流动性未通过固定四折门槛，终止且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "非流动性研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新Top40持仓"),
        ],
    )


def _median(values: list[float]) -> float:
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")


def _data_version(paths: RuntimePaths) -> str:
    """绑定基础与增量行情版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
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
