"""五资产独立趋势槽位的固定多折回测。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import FundPortfolioPanel, load_fund_portfolio_panel
from examples.cross_asset_dual_momentum_study import (
    DEFENSIVE_ASSET,
    FOLDS,
    LOAD_START,
    RISKY_ASSETS,
    STUDY_START,
    build_annual_metrics,
    load_quality_correlation,
)
from examples.cross_asset_independent_trend_feasibility_study import (
    EXPERIMENT_ID as FEASIBILITY_ID,
    FAST_WINDOW,
    SLOW_WINDOW,
)
from examples.cross_asset_independent_trend_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from factors.etf_independent_trend import calculate_independent_trend_states
from factors.etf_momentum import calculate_trailing_momentum, month_end_signal_dates
from portfolio.defensive_rotation import build_defensive_rotation_targets
from portfolio.independent_trend_slots import build_independent_trend_slot_targets
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


STRATEGY_ID = "cross_asset_independent_trend_slots_v1"
DUAL_CONTROL_ID = "cross_asset_dual_momentum_same_data_control"
REPORT_PATH = Path("docs/research/cross-asset-independent-trend-slots-v1.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="五资产独立趋势槽位 V1",
    category="allocation_strategy",
    hypothesis="独立趋势槽位能否避免双动量集中和慢信号造成的尾部回撤",
    definition={
        "asset_pool": {
            "risky": RISKY_ASSETS,
            "defensive": DEFENSIVE_ASSET,
            "economic_roles_fixed": True,
        },
        "signal": {
            "formula": "ma60_gt_ma120",
            "independent_per_asset": True,
            "signal_time": "month_end_close",
        },
        "portfolio": {
            "slot_weight": 0.25,
            "inactive_slot_to": DEFENSIVE_ASSET,
            "relative_ranking": False,
            "rebalance": "monthly",
        },
        "risk_overlay": "none_signal_itself_controls_asset_exposure",
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 5.0,
            "stamp_tax_rate": 0.0,
        },
        "control": {
            "definition": "252d_positive_top2_dual_momentum",
            "same_data_and_execution": True,
        },
        "evaluation": {
            "folds": FOLDS,
            "full_annual_return_min": 0.05,
            "full_max_drawdown_floor": -0.25,
            "full_sharpe_min": 0.60,
            "full_calmar_min": 0.25,
            "full_positive_excess": True,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.40,
            "annual_turnover_max": 4.0,
            "quality_correlation_max": 0.60,
            "dual_full_drawdown_improvement_min": 0.15,
            "dual_early_drawdown_improvement_min": 0.15,
            "dual_annual_return_tolerance": -0.02,
            "parameters_fixed_before_backtest": True,
            "no_follow_up_variants": True,
        },
        "feasibility_dependency": FEASIBILITY_ID,
        "promotion_scope": "research_only",
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记完整语义和数据指纹后执行唯一一次固定回测。"""
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
        result, runs, holdings = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs, holdings)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun], pd.DataFrame]:
    """同一基金面板构造独立趋势候选和旧双动量对照。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*RISKY_ASSETS, DEFENSIVE_ASSET],
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    states = calculate_independent_trend_states(
        panel.adjusted_close,
        signals,
        RISKY_ASSETS,
        fast_window=FAST_WINDOW,
        slow_window=SLOW_WINDOW,
    )
    trend_targets, trend_holdings = build_independent_trend_slot_targets(
        states,
        RISKY_ASSETS,
        DEFENSIVE_ASSET,
    )
    momentum = calculate_trailing_momentum(
        panel.adjusted_close,
        signals,
        RISKY_ASSETS,
        lookback_days=252,
    )
    dual_targets, _ = build_defensive_rotation_targets(
        momentum,
        RISKY_ASSETS,
        DEFENSIVE_ASSET,
        top_n=2,
    )
    benchmark = _benchmark_curve(panel)
    runs = {
        STRATEGY_ID: _run(STRATEGY_ID, trend_targets, panel, benchmark),
        DUAL_CONTROL_ID: _run(DUAL_CONTROL_ID, dual_targets, panel, benchmark),
    }
    periods = {
        key: (
            start,
            panel.latest_common_date if end == "LATEST" else end,
        )
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, panel.latest_common_date)
    metrics = build_period_metrics(
        {key: run.result for key, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(
        runs[STRATEGY_ID],
        benchmark,
        panel.latest_common_date,
    )
    quality_correlation = load_quality_correlation(paths, runs[STRATEGY_ID])
    delta = build_dual_momentum_delta(metrics)
    gate = evaluate_gate(metrics[STRATEGY_ID], quality_correlation, delta)
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": panel.latest_common_date,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "dual_momentum_delta": delta,
        "average_exposure": build_average_exposure(trend_targets),
        "gate": gate,
        "latest_holdings": _latest_records(trend_holdings),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    output = Path(result["report_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    return result, runs, trend_holdings


def _run(
    strategy_id: str,
    targets: dict[str, dict[str, float]],
    panel: FundPortfolioPanel,
    benchmark: pd.Series,
) -> RiskLayerRun:
    """ETF订单继续经过M0，只取消不适用的印花税。"""
    return run_risk_layer_backtest(
        strategy_id,
        "FIXED",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        ExecutionModel(stamp_tax_rate=0.0, slippage_bps=5.0),
    )


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    values = panel.adjusted_close["510300.SH"].astype(float)
    return values / float(values.iloc[0])


def build_dual_momentum_delta(
    metrics: dict[str, dict[str, dict[str, float]]],
) -> dict[str, float]:
    candidate = metrics[STRATEGY_ID]
    control = metrics[DUAL_CONTROL_ID]
    return {
        "full_drawdown_improvement": (
            candidate["full"]["max_drawdown"]
            - control["full"]["max_drawdown"]
        ),
        "early_drawdown_improvement": (
            candidate["2015_2017"]["max_drawdown"]
            - control["2015_2017"]["max_drawdown"]
        ),
        "annual_return_change": (
            candidate["full"]["annualized_return"]
            - control["full"]["annualized_return"]
        ),
        "sharpe_change": (
            candidate["full"]["sharpe"] - control["full"]["sharpe"]
        ),
    }


def evaluate_gate(
    candidate: dict[str, dict[str, float]],
    quality_correlation: float,
    delta: dict[str, float],
) -> dict[str, Any]:
    """执行收益扫描前冻结的绝对、独立性和机制门槛。"""
    full = candidate["full"]
    folds = [candidate[key] for key in FOLDS]
    checks = {
        "full_annual_return_at_least_5pct": full["annualized_return"] >= 0.05,
        "full_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "full_sharpe_at_least_060": full["sharpe"] >= 0.60,
        "full_calmar_at_least_025": full["calmar"] >= 0.25,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_25pct": (
            min(item["max_drawdown"] for item in folds) >= -0.25
        ),
        "median_fold_sharpe_at_least_040": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.40
        ),
        "annual_turnover_below_4x": full["annual_turnover"] <= 4.0,
        "quality_correlation_at_most_060": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.60
        ),
        "dual_full_drawdown_improves_15pct": (
            delta["full_drawdown_improvement"] >= 0.15
        ),
        "dual_early_drawdown_improves_15pct": (
            delta["early_drawdown_improvement"] >= 0.15
        ),
        "dual_return_loss_within_2pct": (
            delta["annual_return_change"] >= -0.02
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def build_average_exposure(
    targets: dict[str, dict[str, float]],
) -> dict[str, float]:
    """计算每个资产的月度平均目标权重。"""
    symbols = [*RISKY_ASSETS, DEFENSIVE_ASSET]
    return {
        symbol: float(
            pd.Series([
                weights.get(symbol, 0.0)
                for weights in targets.values()
            ]).mean()
        )
        for symbol in symbols
    }


def _latest_records(holdings: pd.DataFrame) -> list[dict[str, Any]]:
    latest = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ]
    return latest.to_dict("records")


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("独立趋势槽位数据可行性实验尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("独立趋势槽位数据可行性门禁未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    holdings: pd.DataFrame,
) -> None:
    """保存候选/对照净值、趋势状态和失败也可追踪的结论。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame({
        key: run.result.daily_values / float(run.result.daily_values.iloc[0])
        for key, run in runs.items()
    }).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "monthly_trend_states.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "独立趋势槽位通过多折、低回撤和独立性门槛，仅进入前瞻确认"
            if passed
            else "独立趋势槽位未通过冻结门槛，不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "固定多折研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与双动量净值"),
            ExperimentArtifact("trend_states", holdings_path, "月度趋势状态"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    parts: list[str] = []
    for label, path in [
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
        ("monitoring", paths.monitoring_path),
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
