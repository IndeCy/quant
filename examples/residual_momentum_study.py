"""走步双因子残差动量的固定四折回测。"""

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
from data.intermediate_momentum import materialize_intermediate_momentum
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.residual_momentum import (
    build_style_factor_frame,
    materialize_residual_momentum,
)
from examples.earnings_express_acceleration_study import (
    build_annual_metrics,
    load_quality_correlation,
)
from examples.factor_multifold_revalidation import FOLDS
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from examples.residual_momentum_feasibility_study import (
    EXPERIMENT_ID as FEASIBILITY_ID,
    SOURCE_START,
    load_investable_source,
)
from examples.residual_momentum_report import render_report
from examples.residual_momentum_study_metrics import (
    build_style_residual as _build_style_residual,
    evaluate_gate,
)
from factors.residual_momentum import score_residual_momentum
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


STRATEGY_ID = "residual_momentum_two_factor_v1"
REPORT_PATH = Path("docs/research/residual-momentum-two-factor-v1.md")
STUDY_START = "20150101"
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="走步双因子残差动量 V1",
    category="factor_strategy",
    hypothesis="剔除市场与中盘暴露后的自身趋势能否形成跨阶段可执行Alpha",
    definition={
        "factor": {
            "beta_estimation_window": "signal_lag_252_to_121",
            "residual_window": "signal_lag_120_to_20",
            "market_factor": "510300_qfq_daily_return",
            "size_factor": "510500_qfq_return_minus_510300_qfq_return",
            "direction": "higher_is_better",
        },
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
            "walk_forward_midcap_residual_gate": "all_five_checks",
            "parameters_fixed_before_backtest": True,
            "no_follow_up_variants": True,
        },
        "feasibility_dependency": FEASIBILITY_ID,
        "methodology_version": "multifold_plus_style_residual_v1",
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
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], RiskLayerRun, pd.DataFrame]:
    """构造月度目标并复用既有风险层、基准和M0执行。"""
    hs300 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=as_of_date,
    )
    csi500 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510500.SH",
        end_date=as_of_date,
    )
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start=SOURCE_START,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection, lookback_start=SOURCE_START)
        latest_date = str(
            connection.execute(
                "SELECT MAX(trade_date) FROM features"
            ).fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        materialize_residual_momentum(
            connection,
            build_style_factor_frame(hs300, csi500),
            signal_dates,
            source_start=SOURCE_START,
        )
        # 候选读取器保留普通动量字段，只用于相关性诊断和报告。
        materialize_intermediate_momentum(
            connection,
            source_start=SOURCE_START,
            research_start=STUDY_START,
        )
        candidates = load_investable_source(connection, signal_dates)
        targets, holdings, candidate_counts = build_targets(candidates)
        symbols = sorted(
            holdings["symbol"].astype(str).unique().tolist()
        )
        if not symbols:
            raise ValueError("残差动量没有产生历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = [
            date
            for date in load_trading_calendar(connection)
            if STUDY_START <= date.strftime("%Y%m%d") <= latest_date
        ]
    finally:
        connection.close()
    benchmark = hs300.loc[:pd.Timestamp(latest_date)]
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
    style_residual = build_style_residual(
        paths,
        annual,
        latest_date,
    )
    gate = evaluate_gate(
        metrics,
        quality_correlation,
        style_residual,
    )
    result = _build_result(
        latest_date,
        metrics,
        annual,
        quality_correlation,
        style_residual,
        gate,
        holdings,
        candidate_counts,
        run,
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result["report_path"] = str(report_path)
    report_path.write_text(render_report(result), encoding="utf-8")
    return result, run, holdings


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """逐月选择累计特质收益最高的Top40。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_residual_momentum(group)
        scored["signal_date"] = str(signal_date)
        counts[str(signal_date)] = len(scored)
        if len(scored) >= TOP_N:
            frames.append(scored)
    if not frames:
        empty = candidates.iloc[0:0].assign(
            factor_score=pd.Series(dtype=float)
        )
        return {}, empty, {"min": 0.0, "median": 0.0, "latest": 0.0}
    scores = pd.concat(frames, ignore_index=True)
    mappings, holdings = build_topn_selections(
        scores,
        "factor_score",
        TOP_N,
    )
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


def build_style_residual(
    paths: RuntimePaths,
    annual: dict[str, dict[str, float]],
    latest_date: str,
) -> dict[str, Any]:
    """为研究入口绑定策略ID，避免指标模块感知全局常量。"""
    return _build_style_residual(
        paths,
        annual,
        latest_date,
        STRATEGY_ID,
    )


def _build_result(
    latest_date: str,
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
    style_residual: dict[str, Any],
    gate: dict[str, Any],
    holdings: pd.DataFrame,
    candidate_counts: dict[str, float],
    run: RiskLayerRun,
) -> dict[str, Any]:
    """整理可持久化的研究结果。"""
    latest = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    diagnostics = {
        "selected_residual_momentum_median": float(
            holdings["residual_momentum"].median()
        ),
        "selected_market_beta_median": float(
            holdings["market_beta"].median()
        ),
        "selected_size_beta_median": float(
            holdings["size_beta"].median()
        ),
        "selected_vol60_median": float(holdings["vol60"].median()),
        "selected_adv_median_rmb": float(holdings["adv_rmb"].median()),
    }
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "gate": gate,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "style_residual": style_residual,
        "diagnostics": diagnostics,
        "risk_summary": {
            "average_exposure": float(run.exposure.mean()),
            "reduced_days": float(run.exposure.lt(1.0).sum()),
            "event_count": float(len(run.events)),
        },
        "candidate_counts": candidate_counts,
        "latest_holdings": _records_without_missing(
            latest[
                [
                    "signal_date",
                    "symbol",
                    "name",
                    "rank",
                    "factor_score",
                    "residual_momentum",
                    "market_beta",
                    "size_beta",
                    "ret120",
                    "vol60",
                    "adv_rmb",
                ]
            ]
        ),
        "reused": False,
    }


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    """只接受实验仓库中已通过的数据门禁。"""
    detail = SystemRepository(
        paths.system_state_path
    ).load_experiment_detail(FEASIBILITY_ID)
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("残差动量数据可行性实验尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("残差动量数据可行性门禁未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
    holdings: pd.DataFrame,
) -> None:
    """保存报告、净值和月度目标，不自动注册生产。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame(
        {
            "trade_date": run.result.daily_values.index,
            "strategy_nav": (
                run.result.daily_values
                / float(run.result.daily_values.iloc[0])
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
            "残差动量通过固定多折与风格残差门槛，仅允许前瞻确认"
            if passed
            else "残差动量未通过固定门槛，终止且不注册生产"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "正式研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "净值和风险仓位"),
            ExperimentArtifact(
                "monthly_targets",
                holdings_path,
                "月度目标组合",
            ),
        ],
    )


def _records_without_missing(
    frame: pd.DataFrame,
) -> list[dict[str, Any]]:
    """把缺失值转换为JSON空值。"""
    return [
        {
            key: None if pd.isna(value) else value
            for key, value in row.items()
        }
        for row in frame.to_dict("records")
    ]


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情、增量和ETF文件版本。"""
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
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
