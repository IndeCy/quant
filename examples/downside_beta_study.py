"""低下行 Beta 防御因子的固定四折回测。"""

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
from data.downside_beta import (
    create_downside_beta_signal_dates,
    materialize_downside_beta,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples.downside_beta_feasibility_study import (
    MIN_DOWN_OBSERVATIONS,
    MIN_OBSERVATIONS,
    STUDY_START,
    WINDOW,
    load_investable_panel,
)
from examples.downside_beta_report import render_report
from examples.earnings_express_acceleration_study import (
    build_annual_metrics,
    load_quality_correlation,
)
from examples.factor_multifold_revalidation import FOLDS
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.downside_beta import score_downside_beta_frame
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


STRATEGY_ID = "downside_beta_252d_v1"
REPORT_PATH = Path("docs/research/downside-beta-252d-v1.md")
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="低下行Beta防御因子 V1",
    category="factor_strategy",
    hypothesis="只在市场下跌日具有低联动的股票能否形成跨阶段防御Alpha",
    definition={
        "factor": {
            "formula": (
                "cov(stock_return,510300_return|market_return<0)"
                "/var(510300_return|market_return<0)"
            ),
            "direction": "lower_is_better",
            "window": WINDOW,
            "min_observations": MIN_OBSERVATIONS,
            "min_down_observations": MIN_DOWN_OBSERVATIONS,
            "valid_downside_beta": [0.0, 3.0],
            "valid_total_beta": [0.0, 3.0],
            "transform": "raw_cross_sectional_percentile_rank",
        },
        "prior_research_distinction": {
            "quality_lowbeta_v0": "standalone_down_market_beta_not_quality_blend",
            "low_residual_volatility_120d_v1": (
                "systematic_downside_sensitivity_not_idiosyncratic_volatility"
            ),
            "low_volatility_core": "conditional_market_covariance_not_total_volatility",
        },
        "visibility": {
            "benchmark": "510300.SH_qfq",
            "same_day_close_signal_next_trading_day_execution": True,
            "rolling_window_uses_current_and_past_only": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
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
        "feasibility_dependency": "downside_beta_data_feasibility_v1",
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记冻结指纹后，执行唯一一次正式回测。"""
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
    """构造低下行 Beta 目标，并复用固定风险层与 M0。"""
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
        benchmark = load_adjusted_fund_curve(
            paths.fund_daily_history_path,
            paths.benchmark_increment_path,
            "510300.SH",
            end_date=latest_date,
        )
        create_downside_beta_signal_dates(connection, signal_dates)
        materialize_downside_beta(
            connection,
            benchmark,
            window=WINDOW,
            min_observations=MIN_OBSERVATIONS,
            min_down_observations=MIN_DOWN_OBSERVATIONS,
        )
        candidates = load_investable_panel(connection)
        targets, holdings, candidate_counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("低下行Beta没有产生历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = [
            value
            for value in load_trading_calendar(connection)
            if STUDY_START <= value.strftime("%Y%m%d") <= latest_date
        ]
    finally:
        connection.close()

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
                    "downside_beta",
                    "total_beta",
                    "upside_beta",
                    "amount20_rmb",
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
    """逐月选择下行 Beta 最低的 Top40 并等权。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_downside_beta_frame(group)
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
    """归因总Beta、低波、流动性、动量和市场板块暴露。"""
    correlations: dict[str, list[float]] = {
        "low_total_beta": [],
        "low_vol60": [],
        "amount20_rmb": [],
        "ret120": [],
    }
    overlaps: dict[str, list[float]] = {
        "low_total_beta": [],
        "low_vol60": [],
    }
    cutoff_ties: list[int] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_downside_beta_frame(group)
        if len(scored) < TOP_N:
            continue
        rank = scored["factor_score"].rank()
        comparands = {
            "low_total_beta": -scored["total_beta"],
            "low_vol60": -scored["vol60"],
            "amount20_rmb": scored["amount20_rmb"],
            "ret120": scored["ret120"],
        }
        for key, values in comparands.items():
            value = rank.corr(values.rank())
            if pd.notna(value):
                correlations[key].append(float(value))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        for key, comparator in {
            "low_total_beta": scored.nsmallest(TOP_N, "total_beta"),
            "low_vol60": scored.nsmallest(TOP_N, "vol60"),
        }.items():
            overlaps[key].append(
                len(selected & set(comparator["symbol"].astype(str))) / TOP_N
            )
        cutoff = scored["factor_score"].nlargest(TOP_N).iloc[-1]
        cutoff_ties.append(int(scored["factor_score"].eq(cutoff).sum()))
    latest = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ]
    symbols = latest["symbol"].astype(str)
    return {
        "median_spearman_with_low_total_beta": _median(
            correlations["low_total_beta"]
        ),
        "median_spearman_with_low_vol60": _median(
            correlations["low_vol60"]
        ),
        "median_spearman_with_amount20": _median(
            correlations["amount20_rmb"]
        ),
        "median_spearman_with_ret120": _median(correlations["ret120"]),
        "median_top40_overlap_with_low_total_beta": _median(
            overlaps["low_total_beta"]
        ),
        "median_top40_overlap_with_low_vol60": _median(overlaps["low_vol60"]),
        "selected_downside_beta_median": float(holdings["downside_beta"].median()),
        "selected_total_beta_median": float(holdings["total_beta"].median()),
        "selected_upside_beta_median": float(holdings["upside_beta"].median()),
        "selected_vol60_median": float(holdings["vol60"].median()),
        "latest_bj_share": float(symbols.str.endswith(".BJ").mean()),
        "latest_star_share": float(
            symbols.str.match(r"^(688|689)").mean()
        ),
        "latest_chinext_share": float(
            symbols.str.match(r"^(300|301)").mean()
        ),
        "maximum_cutoff_tie_count": float(max(cutoff_ties)),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """执行冻结的四折、风险、换手和独立性门槛。"""
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
    """把研究产物缺失值转换为 JSON null。"""
    return [
        {key: None if pd.isna(value) else value for key, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档报告和最新持仓，失败策略同样保留指纹。"""
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
            "低下行Beta通过固定四折门槛，允许进入独立确认"
            if passed
            else "低下行Beta未通过固定四折门槛，终止且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "低下行Beta研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新Top40持仓"),
        ],
    )


def _median(values: list[float]) -> float:
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情与基准文件版本。"""
    parts: list[str] = []
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
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
