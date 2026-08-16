"""净经营资产异常因子的固定四折回测。"""

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
from data.net_operating_assets import (
    NetOperatingAssetsPaths,
    attach_net_operating_assets_database,
    create_net_operating_assets_signal_dates,
    materialize_net_operating_assets_asof,
)
from examples.earnings_express_acceleration_study import (
    build_annual_metrics,
    load_quality_correlation,
)
from examples.factor_multifold_revalidation import FOLDS
from examples.net_operating_assets_feasibility_study import (
    EXPERIMENT_ID as FEASIBILITY_ID,
    STUDY_START,
    load_investable_source,
)
from examples.net_operating_assets_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from factors.net_operating_assets import score_net_operating_assets
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


STRATEGY_ID = "net_operating_assets_v1"
REPORT_PATH = Path("docs/research/net-operating-assets-v1.md")
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="净经营资产异常 V1",
    category="factor_strategy",
    hypothesis="较低经营资产累积能否形成跨阶段、可执行且独立的A股Alpha",
    definition={
        "factor": {
            "formula": (
                "[(total_assets-money_cap-trad_asset)-"
                "(total_liab-st_borr-lt_borr-bond_payable-"
                "st_bonds_payable-non_cur_liab_due_1y-lease_liab)]"
                "/total_assets"
            ),
            "direction": "lower_is_better",
            "optional_missing_components": "zero_with_missingness_audit",
            "transform": "raw_cross_sectional_percentile_rank",
        },
        "visibility": {
            "annual_1231_only": True,
            "f_ann_date_lte_signal_date": True,
            "latest_visible_revision": True,
            "report_freshness_years": [1, 2],
        },
        "company_type": "1_general_industry",
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {
            "top_n": TOP_N,
            "weight": "equal",
            "rebalance": "monthly",
        },
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
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记冻结指纹后执行唯一一次正式回测。"""
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
        result, run, holdings = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, run, holdings)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], RiskLayerRun, pd.DataFrame]:
    """构造 NOA 目标并复用 GRID 风险层与 M0。"""
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
        create_net_operating_assets_signal_dates(connection, signal_dates)
        attach_net_operating_assets_database(
            connection,
            NetOperatingAssetsPaths(paths.balance_sheet_path),
        )
        materialize_net_operating_assets_asof(connection)
        candidates = load_investable_source(connection)
        targets, holdings, candidate_counts = build_targets(candidates)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("净经营资产因子没有产生历史持仓")
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
    metrics = build_period_metrics(
        {STRATEGY_ID: run.result},
        benchmark,
        periods,
    )[STRATEGY_ID]
    annual = build_annual_metrics(run, benchmark, latest_date)
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, quality_correlation)
    diagnostics = build_diagnostics(holdings)
    risk_summary = {
        "average_exposure": float(run.exposure.mean()),
        "reduced_days": float(run.exposure.lt(1.0).sum()),
        "event_count": float(len(run.events)),
    }
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
            risk_summary,
            candidate_counts,
            latest_date,
        ),
        encoding="utf-8",
    )
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "gate": gate,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "diagnostics": diagnostics,
        "risk_summary": risk_summary,
        "candidate_counts": candidate_counts,
        "latest_holdings": _records_without_missing(
            latest_holdings[
                [
                    "signal_date",
                    "symbol",
                    "name",
                    "rank",
                    "factor_score",
                    "noa_ratio",
                    "ret120",
                    "vol60",
                    "adv_rmb",
                    "report_period",
                    "publish_date",
                    "trad_asset_missing",
                    "all_debt_components_missing",
                ]
            ]
        ),
        "report_path": str(report_path),
        "reused": False,
    }
    return result, run, holdings


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """逐月选择净经营资产强度最低的 Top40。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_net_operating_assets(group)
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


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """执行冻结的多折、回撤、换手和独立性门槛。"""
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
            float(pd.Series([item["sharpe"] for item in folds]).median())
            >= 0.35
        ),
        "annual_turnover_below_10x": full["annual_turnover"] <= 10.0,
        "quality_correlation_at_most_075": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.75
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


def build_diagnostics(holdings: pd.DataFrame) -> dict[str, float]:
    """记录实际入选股票的 NOA、风险、流动性和缺失情况。"""
    cutoff_ties: list[int] = []
    for _, group in holdings.groupby("signal_date", sort=True):
        cutoff = group["factor_score"].nlargest(TOP_N).iloc[-1]
        cutoff_ties.append(int(group["factor_score"].eq(cutoff).sum()))
    return {
        "selected_noa_ratio_median": float(holdings["noa_ratio"].median()),
        "selected_ret120_median": float(holdings["ret120"].median()),
        "selected_vol60_median": float(holdings["vol60"].median()),
        "selected_adv_median_rmb": float(holdings["adv_rmb"].median()),
        "selected_trading_asset_missing_share": float(
            holdings["trad_asset_missing"].mean()
        ),
        "selected_all_debt_missing_share": float(
            holdings["all_debt_components_missing"].mean()
        ),
        "maximum_cutoff_tie_count": float(max(cutoff_ties)),
    }


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    """只信任实验仓库中最新成功的数据门禁。"""
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("净经营资产数据可行性实验尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("净经营资产数据可行性门禁未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
    holdings: pd.DataFrame,
) -> None:
    """保存报告、净值和完整月度目标，失败结果也可回溯。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame(
        {
            "trade_date": run.result.daily_values.index,
            "strategy_nav": (
                run.result.daily_values / float(run.result.daily_values.iloc[0])
            ).values,
            "target_exposure": run.exposure.reindex(
                run.result.daily_values.index
            ).values,
        }
    ).to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "monthly_targets.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "净经营资产通过固定四折门槛，仅允许进入独立前瞻确认"
            if passed
            else "净经营资产未通过固定四折门槛，终止且不注册生产"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "正式研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "策略净值和风险仓位"),
            ExperimentArtifact("monthly_targets", holdings_path, "月度目标组合"),
        ],
    )


def _records_without_missing(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """把研究产物缺失值转换为 JSON null。"""
    return [
        {key: None if pd.isna(value) else value for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _data_version(paths: RuntimePaths) -> str:
    """绑定财务、行情、增量和基准文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("balance", paths.balance_sheet_path),
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
