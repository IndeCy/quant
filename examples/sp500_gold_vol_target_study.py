"""标普500与黄金60/40风险块的12%波动目标机会成本研究。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import load_fund_portfolio_panel
from examples import global_defensive_equal_study as global_study
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from examples.sp500_gold_vol_target_report import render_report
from factors.etf_momentum import month_end_signal_dates
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "sp500_gold_60_40_vol_target_12_v1"
REPORT_PATH = Path("docs/research/sp500-gold-vol-target-12-v1.md")
SP500 = "513500.SH"
GOLD = "518880.SH"
BOND = "511010.SH"
BENCHMARK = "510300.SH"
RISK_BLOCK = {SP500: 0.60, GOLD: 0.40}
TARGET_VOLATILITY = 0.12
LOOKBACK = 63
SIGNAL_START = "20140401"
OOS_START = "20190101"
LOCKED_START = "20220101"
PERIODS = {
    "2019_2021": ("20190101", "20211231"),
    "2022_2024": ("20220101", "20241231"),
    "2025_latest": ("20250101", "LATEST"),
    "locked_test": (LOCKED_START, "LATEST"),
    "oos_full": (OOS_START, "LATEST"),
}
FOLD_KEYS = ("2019_2021", "2022_2024", "2025_latest")
VOL_CONTROL_ID = "sp500_direct_vol_target_12_control"
DIRECT_ID = "sp500_direct_control_for_vol_target"
STRESS_ID = "sp500_gold_60_40_vol_target_12_cost_20bps"

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="标普500 × 黄金60/40块 12%波动目标 V1",
    category="allocation_strategy",
    hypothesis=(
        "在候选和简单标普对照使用同一波动目标机制时，"
        "黄金分散能否产生扣成本后的真实机会成本优势"
    ),
    definition={
        "candidate_risk_block": {
            "assets": RISK_BLOCK,
            "weight_grid": False,
        },
        "simple_control_risk_block": {SP500: 1.0},
        "shared_risk_budget": {
            "target_annualized_volatility": TARGET_VOLATILITY,
            "lookback_trading_days": LOOKBACK,
            "signal": "month_end_close",
            "effective": "next_trading_day",
            "leverage_cap": 1.0,
            "unused_budget_asset": BOND,
            "same_mechanism_for_candidate_and_control": True,
        },
        "absolute_opportunity_cost": {SP500: 1.0},
        "evaluation": {
            "oos_start": OOS_START,
            "locked_start": LOCKED_START,
            "periods": PERIODS,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "stamp_tax_rate": 0.0,
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
        },
        "frozen_gate": {
            "oos_return_min": 0.10,
            "oos_drawdown_floor": -0.20,
            "oos_sharpe_min": 0.90,
            "oos_calmar_min": 0.55,
            "return_lift_vs_same_mechanism_control_min": 0.01,
            "sharpe_lift_vs_same_mechanism_control_min": 0.10,
            "drawdown_worse_vs_same_mechanism_control_max": 0.01,
            "volatility_worse_vs_same_mechanism_control_max": 0.01,
            "volatility_reduction_vs_direct_min": 0.20,
            "drawdown_improvement_vs_direct_min": 0.05,
            "return_shortfall_vs_direct_max": 0.03,
            "all_three_folds_positive": True,
            "worst_fold_drawdown_floor": -0.20,
            "median_fold_sharpe_min": 0.70,
            "locked_return_min": 0.10,
            "locked_drawdown_floor": -0.18,
            "locked_sharpe_min": 0.85,
            "positive_years_min": 6,
            "annual_turnover_max": 1.5,
            "average_risk_allocation_min": 0.60,
            "stress_return_lift_vs_control_min": 0.007,
            "stress_sharpe_min": 0.85,
            "worst_day_floor": -0.08,
            "expected_shortfall_95_floor": -0.025,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "shared_vol_target_opportunity_cost_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记共同机制与门槛后，才读取完整基金行情。"""
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
        result, runs, targets, diagnostics = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs, targets, diagnostics)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    dict[str, Any],
    dict[str, RiskLayerRun],
    dict[str, dict[str, dict[str, float]]],
    dict[str, Any],
]:
    global_study._require_feasibility_passed(paths)
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [SP500, GOLD, BOND, BENCHMARK],
        start_date="20140101",
        end_date=as_of_date,
    )
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(SIGNAL_START)
    ]
    candidate_targets = build_vol_target_targets(
        panel.adjusted_close,
        signals,
        RISK_BLOCK,
    )
    control_targets = build_vol_target_targets(
        panel.adjusted_close,
        signals,
        {SP500: 1.0},
    )
    direct_targets = global_study._build_targets(signals, {SP500: 1.0})
    target_sets = {
        EXPERIMENT_ID: candidate_targets,
        VOL_CONTROL_ID: control_targets,
        DIRECT_ID: direct_targets,
        STRESS_ID: candidate_targets,
    }
    benchmark = global_study._benchmark_curve(panel)
    runs = {
        strategy_id: run_risk_layer_backtest(
            strategy_id,
            "VOL_TARGET",
            targets,
            panel.bars,
            panel.calendar,
            benchmark,
            ExecutionModel(
                stamp_tax_rate=0.0,
                slippage_bps=20.0 if strategy_id == STRESS_ID else 5.0,
            ),
        )
        for strategy_id, targets in target_sets.items()
    }
    periods = {
        name: (start, panel.latest_common_date if end == "LATEST" else end)
        for name, (start, end) in PERIODS.items()
    }
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual_all = build_annual_metrics(
        runs,
        benchmark,
        panel.latest_common_date,
    )
    annual = {
        strategy_id: {
            year: item
            for year, item in values.items()
            if year >= OOS_START[:4]
        }
        for strategy_id, values in annual_all.items()
    }
    diagnostics = build_diagnostics(
        paths,
        runs,
        candidate_targets,
        control_targets,
    )
    gate = evaluate_gate(metrics, annual, diagnostics)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "period_metrics": metrics[EXPERIMENT_ID],
        "period_comparison": metrics,
        "annual_comparison": annual,
        "diagnostics": diagnostics,
        "gate": gate,
        "latest_holdings": [
            {
                "signal_date": max(candidate_targets),
                "symbol": symbol,
                "target_weight": weight,
            }
            for symbol, weight in candidate_targets[
                max(candidate_targets)
            ].items()
        ],
        "decision": (
            "FORWARD_PAPER_REQUIRED" if gate["passed"] else "REJECTED"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report_path = Path(result["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    return result, runs, target_sets, diagnostics


def build_vol_target_targets(
    adjusted_close: pd.DataFrame,
    signals: list[pd.Timestamp],
    risk_block: dict[str, float],
) -> dict[str, dict[str, float]]:
    """只使用信号日及之前63日收益估算风险预算。"""
    if not math.isclose(sum(risk_block.values()), 1.0):
        raise ValueError("risk block weights must sum to one")
    if BOND in risk_block:
        raise ValueError("risk block cannot contain the unused-budget asset")
    symbols = list(risk_block)
    returns = (
        adjusted_close[symbols]
        .pct_change(fill_method=None)
        .dropna()
    )
    targets: dict[str, dict[str, float]] = {}
    for signal in signals:
        history = returns.loc[:signal].tail(LOOKBACK)
        if len(history) < LOOKBACK:
            continue
        block_return = sum(
            float(weight) * history[symbol]
            for symbol, weight in risk_block.items()
        )
        volatility = float(block_return.std(ddof=1) * math.sqrt(252))
        if not math.isfinite(volatility) or volatility <= 0:
            raise ValueError(f"invalid trailing volatility at {signal}")
        risk_allocation = min(1.0, TARGET_VOLATILITY / volatility)
        weights = {
            symbol: weight * risk_allocation
            for symbol, weight in risk_block.items()
        }
        weights[BOND] = 1.0 - risk_allocation
        targets[signal.strftime("%Y%m%d")] = weights
    if not targets:
        raise ValueError("volatility target produced no signals")
    return targets


def build_diagnostics(
    paths: RuntimePaths,
    runs: dict[str, RiskLayerRun],
    candidate_targets: dict[str, dict[str, float]],
    control_targets: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """验证实际风险匹配、风险预算、尾部和独立性。"""
    navs = {
        key: run.result.daily_values.loc[OOS_START:].astype(float)
        for key, run in runs.items()
    }
    candidate_returns = navs[EXPERIMENT_ID].pct_change().dropna()
    threshold = float(candidate_returns.quantile(0.05))
    drawdown = (
        navs[EXPERIMENT_ID] / navs[EXPERIMENT_ID].cummax() - 1.0
    )
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift(fill_value=False)).cumsum()
    lengths = underwater.groupby(groups).sum()
    candidate_allocations = [
        1.0 - weights.get(BOND, 0.0)
        for date, weights in candidate_targets.items()
        if date >= OOS_START
    ]
    control_allocations = [
        1.0 - weights.get(BOND, 0.0)
        for date, weights in control_targets.items()
        if date >= OOS_START
    ]
    return {
        "candidate_volatility": _annualized_volatility(
            navs[EXPERIMENT_ID]
        ),
        "vol_target_control_volatility": _annualized_volatility(
            navs[VOL_CONTROL_ID]
        ),
        "direct_sp500_volatility": _annualized_volatility(navs[DIRECT_ID]),
        "candidate_average_risk_allocation": float(
            pd.Series(candidate_allocations).mean()
        ),
        "candidate_min_risk_allocation": min(candidate_allocations),
        "candidate_max_risk_allocation": max(candidate_allocations),
        "control_average_risk_allocation": float(
            pd.Series(control_allocations).mean()
        ),
        "worst_day": float(candidate_returns.min()),
        "value_at_risk_95": threshold,
        "expected_shortfall_95": float(
            candidate_returns[candidate_returns.le(threshold)].mean()
        ),
        "max_underwater_days": int(lengths.max()) if len(lengths) else 0,
        "quality_correlation": global_study.load_quality_correlation(
            paths,
            runs[EXPERIMENT_ID],
        ),
    }


def _annualized_volatility(nav: pd.Series) -> float:
    returns = nav.pct_change().dropna()
    return float(returns.std(ddof=1) * math.sqrt(252))


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, dict[str, float]]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    """按共同风险机制的机会成本门槛验收。"""
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["oos_full"]
    locked = candidate["locked_test"]
    control = metrics[VOL_CONTROL_ID]["oos_full"]
    direct = metrics[DIRECT_ID]["oos_full"]
    stress = metrics[STRESS_ID]["oos_full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    return_lift_control = (
        full["annualized_return"] - control["annualized_return"]
    )
    sharpe_lift_control = full["sharpe"] - control["sharpe"]
    drawdown_gap_control = (
        abs(full["max_drawdown"]) - abs(control["max_drawdown"])
    )
    volatility_gap_control = (
        diagnostics["candidate_volatility"]
        - diagnostics["vol_target_control_volatility"]
    )
    return_lift_direct = (
        full["annualized_return"] - direct["annualized_return"]
    )
    volatility_reduction_direct = 1.0 - (
        diagnostics["candidate_volatility"]
        / diagnostics["direct_sp500_volatility"]
    )
    drawdown_improvement_direct = (
        full["max_drawdown"] - direct["max_drawdown"]
    )
    positive_years = sum(
        item["annualized_return"] > 0
        for item in annual[EXPERIMENT_ID].values()
    )
    checks = {
        "oos_annual_return_at_least_10pct": (
            full["annualized_return"] >= 0.10
        ),
        "oos_drawdown_within_20pct": full["max_drawdown"] >= -0.20,
        "oos_sharpe_at_least_090": full["sharpe"] >= 0.90,
        "oos_calmar_at_least_055": full["calmar"] >= 0.55,
        "return_lift_vs_same_mechanism_control_at_least_1pct": (
            return_lift_control >= 0.01
        ),
        "sharpe_lift_vs_same_mechanism_control_at_least_010": (
            sharpe_lift_control >= 0.10
        ),
        "drawdown_worse_vs_same_mechanism_control_within_1pct": (
            drawdown_gap_control <= 0.01
        ),
        "volatility_worse_vs_same_mechanism_control_within_1pct": (
            volatility_gap_control <= 0.01
        ),
        "volatility_reduction_vs_direct_at_least_20pct": (
            volatility_reduction_direct >= 0.20
        ),
        "drawdown_improvement_vs_direct_at_least_5pct": (
            drawdown_improvement_direct >= 0.05
        ),
        "return_shortfall_vs_direct_within_3pct": (
            return_lift_direct >= -0.03
        ),
        "all_three_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_20pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.20,
        "median_fold_sharpe_at_least_070": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.70,
        "locked_return_at_least_10pct": (
            locked["annualized_return"] >= 0.10
        ),
        "locked_drawdown_within_18pct": (
            locked["max_drawdown"] >= -0.18
        ),
        "locked_sharpe_at_least_085": locked["sharpe"] >= 0.85,
        "at_least_six_positive_years": positive_years >= 6,
        "annual_turnover_below_15x": full["annual_turnover"] <= 1.5,
        "average_risk_allocation_at_least_60pct": (
            diagnostics["candidate_average_risk_allocation"] >= 0.60
        ),
        "stress_return_lift_vs_control_at_least_07pct": (
            stress["annualized_return"]
            - control["annualized_return"]
            >= 0.007
        ),
        "stress_sharpe_at_least_085": stress["sharpe"] >= 0.85,
        "worst_day_within_8pct": diagnostics["worst_day"] >= -0.08,
        "expected_shortfall_95_within_25pct": (
            diagnostics["expected_shortfall_95"] >= -0.025
        ),
        "quality_correlation_at_most_050": (
            abs(diagnostics["quality_correlation"]) <= 0.50
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "return_lift_vs_vol_target_control": return_lift_control,
        "sharpe_lift_vs_vol_target_control": sharpe_lift_control,
        "drawdown_gap_vs_vol_target_control": drawdown_gap_control,
        "volatility_gap_vs_vol_target_control": volatility_gap_control,
        "return_lift_vs_direct_sp500": return_lift_direct,
        "volatility_reduction_vs_direct_sp500": (
            volatility_reduction_direct
        ),
        "drawdown_improvement_vs_direct_sp500": (
            drawdown_improvement_direct
        ),
        "positive_years": positive_years,
    }


def build_decision_reason(gate: dict[str, Any]) -> str:
    """记录所有实际失败的冻结门槛。"""
    if gate["passed"]:
        return "共同12%波动目标候选通过全部机会成本门槛，仅允许前向Paper"
    failed = [name for name, passed in gate["checks"].items() if not passed]
    return f"共同12%波动目标候选未通过门槛（{', '.join(failed)}），归档且不注册"


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, dict[str, float]]],
    diagnostics: dict[str, Any],
) -> None:
    """保存净值、年度、完整目标与尾部诊断。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav_comparison.csv"
    pd.DataFrame(
        {
            strategy_id: run.result.daily_values
            / float(run.result.daily_values.iloc[0])
            for strategy_id, run in runs.items()
        }
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    targets_path = attempt.output_dir / "monthly_targets.csv"
    pd.DataFrame(
        [
            {
                "strategy_id": strategy_id,
                "signal_date": date,
                "symbol": symbol,
                "target_weight": weight,
            }
            for strategy_id, strategy_targets in targets.items()
            for date, weights in strategy_targets.items()
            for symbol, weight in weights.items()
        ]
    ).to_csv(targets_path, index=False)
    annual_path = attempt.output_dir / "annual_comparison.csv"
    pd.DataFrame(
        [
            {
                "strategy_id": strategy_id,
                "year": year,
                **item,
            }
            for strategy_id, values in result["annual_comparison"].items()
            for year, item in values.items()
        ]
    ).to_csv(annual_path, index=False)
    diagnostics_path = attempt.output_dir / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=build_decision_reason(result["gate"]),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "共同机制机会成本报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("monthly_targets", targets_path, "月度风险预算目标"),
            ExperimentArtifact("annual_metrics", annual_path, "年度机会成本比较"),
            ExperimentArtifact(
                "diagnostics",
                diagnostics_path,
                "实际风险匹配、尾部和相关性诊断",
            ),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定基金历史、增量和Quality监控版本。"""
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
