"""黄金趋势有效时持有黄金，否则切换国债的月频研究。"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import FundPortfolioPanel, load_fund_portfolio_panel
from examples.cross_asset_dual_momentum_study import (
    FOLDS,
    STUDY_START,
    build_annual_metrics,
    load_quality_correlation,
)
from examples.gold_trend_bond_switch_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from factors.etf_independent_trend import calculate_independent_trend_states
from factors.etf_momentum import month_end_signal_dates
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


STRATEGY_ID = "gold_trend_bond_switch_v1"
REPORT_PATH = Path("docs/research/gold-trend-bond-switch-v1.md")
GOLD_SYMBOL = "518880.SH"
BOND_SYMBOL = "511010.SH"
BENCHMARK_SYMBOL = "510300.SH"
FAST_WINDOW = 60
SLOW_WINDOW = 120
FEASIBILITY_ID = "cross_asset_independent_trend_data_feasibility_v1"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="黄金趋势国债切换 V1",
    category="allocation_strategy",
    hypothesis="黄金时间序列趋势与国债防守切换能否提供优于固定黄金国债的风险收益",
    definition={
        "asset_pool": {
            "risk_asset": GOLD_SYMBOL,
            "defensive_asset": BOND_SYMBOL,
            "benchmark": BENCHMARK_SYMBOL,
        },
        "signal": {
            "formula": "gold_ma60_gt_ma120",
            "signal_time": "month_end_close",
            "future_data": "forbidden",
        },
        "portfolio": {
            "trend_active": {GOLD_SYMBOL: 1.0},
            "trend_inactive": {BOND_SYMBOL: 1.0},
            "rebalance": "monthly",
            "leverage": 1.0,
        },
        "controls": {
            "gold_only": {GOLD_SYMBOL: 1.0},
            "gold_bond_equal": {GOLD_SYMBOL: 0.5, BOND_SYMBOL: 0.5},
        },
        "risk_overlay": "none",
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 5.0,
            "stamp_tax_rate": 0.0,
        },
        "evaluation": {
            "folds": FOLDS,
            "full_annual_return_min": 0.065,
            "full_max_drawdown_floor": -0.15,
            "full_sharpe_min": 0.90,
            "full_calmar_min": 0.40,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.20,
            "median_fold_sharpe_min": 0.55,
            "annual_turnover_max": 3.0,
            "quality_correlation_max": 0.30,
            "positive_years_min": 8,
            "gold_drawdown_improvement_min": 0.10,
            "gold_return_shortfall_max": 0.025,
            "gold_bond_return_shortfall_max": 0.01,
            "gold_bond_drawdown_improvement_min": 0.02,
            "gold_bond_sharpe_not_lower": True,
            "active_day_share_range": [0.25, 0.80],
            "parameters_fixed_before_backtest": True,
        },
        "feasibility_dependency": FEASIBILITY_ID,
        "promotion_scope": "forward_paper_only",
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在读取基金行情前登记完整研究和数据指纹。"""
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
        result, run, states = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, run, states)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], RiskLayerRun, pd.DataFrame]:
    """在同一qfq面板运行切换策略和两个固定持有对照。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [GOLD_SYMBOL, BOND_SYMBOL, BENCHMARK_SYMBOL],
        start_date="20130101",
        end_date=as_of_date,
    )
    _validate_panel(panel, as_of_date)
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    states = calculate_independent_trend_states(
        panel.adjusted_close,
        signals,
        [GOLD_SYMBOL],
        fast_window=FAST_WINDOW,
        slow_window=SLOW_WINDOW,
    )
    targets, _ = build_independent_trend_slot_targets(
        states,
        [GOLD_SYMBOL],
        BOND_SYMBOL,
    )
    controls = {
        "黄金单资产": {
            date.strftime("%Y%m%d"): {GOLD_SYMBOL: 1.0}
            for date in signals
        },
        "黄金国债50/50": {
            date.strftime("%Y%m%d"): {
                GOLD_SYMBOL: 0.5,
                BOND_SYMBOL: 0.5,
            }
            for date in signals
        },
    }
    benchmark = _benchmark_curve(panel)
    runs = {
        STRATEGY_ID: _run(STRATEGY_ID, targets, panel, benchmark),
        **{
            name: _run(name, control, panel, benchmark)
            for name, control in controls.items()
        },
    }
    periods = {
        key: (start, panel.latest_common_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, panel.latest_common_date)
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    candidate = runs[STRATEGY_ID]
    annual = build_annual_metrics(
        candidate,
        benchmark,
        panel.latest_common_date,
    )
    full_comparison = {
        name: values["full"] for name, values in metrics.items()
    }
    attribution = build_state_attribution(candidate, states, panel.calendar)
    quality_correlation = load_quality_correlation(paths, candidate)
    gate = evaluate_gate(
        metrics[STRATEGY_ID],
        annual,
        quality_correlation,
        full_comparison,
        attribution,
    )
    latest = states.sort_values("signal_date").iloc[-1]
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": panel.latest_common_date,
        "period_metrics": metrics[STRATEGY_ID],
        "annual_metrics": annual,
        "full_comparison": full_comparison,
        "state_attribution": attribution,
        "quality_return_correlation": quality_correlation,
        "latest_state": {
            "signal_date": str(latest["signal_date"]),
            "trend_active": bool(latest["trend_active"]),
            "ma60": float(latest["ma60"]),
            "ma120": float(latest["ma120"]),
        },
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, candidate, states


def build_state_attribution(
    run: RiskLayerRun,
    states: pd.DataFrame,
    calendar: list[pd.Timestamp],
) -> dict[str, dict[str, float]]:
    """按T+1生效状态拆解策略日收益来源。"""
    index = pd.DatetimeIndex(calendar)
    effective: dict[pd.Timestamp, str] = {}
    for row in states.itertuples(index=False):
        signal = pd.Timestamp(str(row.signal_date))
        location = int(index.searchsorted(signal, side="right"))
        if location < len(index):
            effective[index[location]] = (
                "GOLD_ACTIVE" if bool(row.trend_active) else "BOND_DEFENSIVE"
            )
    labels = pd.Series(index=index, dtype="object")
    for date, label in effective.items():
        labels.at[date] = label
    labels = labels.ffill()
    returns = run.result.daily_values.pct_change().rename("return")
    frame = pd.concat([returns, labels.rename("state")], axis=1).dropna()
    result: dict[str, dict[str, float]] = {}
    for state, group in frame.groupby("state", sort=True):
        values = group["return"].astype(float)
        cumulative = float((1.0 + values).prod() - 1.0)
        annualized = (
            float((1.0 + cumulative) ** (252.0 / len(values)) - 1.0)
            if cumulative > -1.0
            else -1.0
        )
        result[str(state)] = {
            "days": int(len(values)),
            "day_share": float(len(values) / len(frame)),
            "cumulative_return": cumulative,
            "annualized_return": annualized,
            "positive_day_ratio": float(values.gt(0).mean()),
            "log_return_contribution": float(
                values.map(lambda value: math.log1p(value)).sum()
            ),
        }
    return result


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
    full_comparison: dict[str, dict[str, float]],
    state_attribution: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """执行绝对、相对、稳定性和状态广度门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    gold = full_comparison["黄金单资产"]
    gold_bond = full_comparison["黄金国债50/50"]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    active_share = state_attribution.get("GOLD_ACTIVE", {}).get("day_share", 0.0)
    checks = {
        "full_annual_return_at_least_65pct": full["annualized_return"] >= 0.065,
        "full_drawdown_within_15pct": full["max_drawdown"] >= -0.15,
        "full_sharpe_at_least_090": full["sharpe"] >= 0.90,
        "full_calmar_at_least_040": full["calmar"] >= 0.40,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_20pct": (
            min(item["max_drawdown"] for item in folds) >= -0.20
        ),
        "median_fold_sharpe_at_least_055": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.55
        ),
        "annual_turnover_below_3x": full["annual_turnover"] <= 3.0,
        "quality_correlation_at_most_030": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.30
        ),
        "at_least_eight_positive_years": positive_years >= 8,
        "gold_drawdown_improvement_at_least_10pct": (
            full["max_drawdown"] - gold["max_drawdown"] >= 0.10
        ),
        "gold_return_shortfall_within_25pct": (
            gold["annualized_return"] - full["annualized_return"] <= 0.025
        ),
        "gold_bond_return_shortfall_within_1pct": (
            gold_bond["annualized_return"] - full["annualized_return"] <= 0.01
        ),
        "gold_bond_drawdown_improvement_at_least_2pct": (
            full["max_drawdown"] - gold_bond["max_drawdown"] >= 0.02
        ),
        "gold_bond_sharpe_not_lower": full["sharpe"] >= gold_bond["sharpe"],
        "active_day_share_between_25_and_80pct": 0.25 <= active_share <= 0.80,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
        "active_day_share": active_share,
    }


def _run(
    name: str,
    targets: dict[str, dict[str, float]],
    panel: FundPortfolioPanel,
    benchmark: pd.Series,
) -> RiskLayerRun:
    return run_risk_layer_backtest(
        name,
        "FIXED",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        ExecutionModel(stamp_tax_rate=0.0, slippage_bps=5.0),
    )


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    values = panel.adjusted_close[BENCHMARK_SYMBOL].astype(float)
    return values / float(values.iloc[0])


def _validate_panel(panel: FundPortfolioPanel, as_of_date: str) -> None:
    if {str(item["symbol"]) for item in panel.coverage} != {
        GOLD_SYMBOL,
        BOND_SYMBOL,
        BENCHMARK_SYMBOL,
    }:
        raise ValueError("黄金、国债或基准基金面板不完整")
    lag = (pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)).days
    if lag < 0 or lag > 5:
        raise ValueError("基金共同数据截止日滞后超过5个自然日")


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("跨资产统一基金数据门禁尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("跨资产统一基金数据门禁未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
    states: pd.DataFrame,
) -> None:
    """保存报告、净值和月度趋势状态。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    values = run.result.daily_values
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame(
        {
            "trade_date": values.index,
            "strategy_nav": values / float(values.iloc[0]),
        }
    ).to_csv(nav_path, index=False)
    states_path = attempt.output_dir / "monthly_trend_states.csv"
    states.to_csv(states_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "黄金趋势国债切换通过多折门槛，可进入前瞻Paper确认"
            if passed
            else "黄金趋势国债切换未通过固定门槛，不创建观察策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "趋势切换研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "每日净值曲线"),
            ExperimentArtifact("monthly_trend_states", states_path, "月度趋势状态"),
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
