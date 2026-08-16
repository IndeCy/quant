"""标普500与黄金固定60/40的严格机会成本研究。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import FundPortfolioPanel, load_fund_portfolio_panel
from examples import global_defensive_equal_study as global_study
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from examples.sp500_gold_opportunity_cost_report import render_report
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


EXPERIMENT_ID = "sp500_gold_60_40_opportunity_cost_v1"
REPORT_PATH = Path(
    "docs/research/sp500-gold-60-40-opportunity-cost-v1.md"
)
SP500 = "513500.SH"
GOLD = "518880.SH"
BOND = "511010.SH"
BENCHMARK = "510300.SH"
CANDIDATE_WEIGHTS = {SP500: 0.60, GOLD: 0.40}
NOMINAL_CONTROL_WEIGHTS = {SP500: 0.60, BOND: 0.40}
CALIBRATION_START = "20140115"
CALIBRATION_END = "20181231"
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
NOMINAL_CONTROL_ID = "sp500_bond_60_40_nominal_control"
RISK_CONTROL_ID = "sp500_bond_calibration_risk_matched_control"
DIRECT_ID = "sp500_direct_control"
STRESS_ID = "sp500_gold_60_40_cost_20bps"

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="标普500 × 黄金固定60/40机会成本 V1",
    category="allocation_strategy",
    hypothesis=(
        "境内标普500ETF与人民币黄金固定60/40，能否在显著低于直接持有"
        "标普500的风险下，净胜校准期冻结的标普500+国债同波动简单组合"
    ),
    definition={
        "candidate": {
            "assets": CANDIDATE_WEIGHTS,
            "weight_basis": "canonical_60_40_fixed_before_backtest",
            "weight_grid": False,
            "rebalance": "monthly",
        },
        "opportunity_cost_controls": {
            "direct_sp500": {SP500: 1.0},
            "same_nominal_weights": NOMINAL_CONTROL_WEIGHTS,
            "risk_matched_simple": {
                "assets": [SP500, BOND],
                "calibration_period": [CALIBRATION_START, CALIBRATION_END],
                "target": "candidate_daily_return_volatility",
                "solver": "closed_form_quadratic_choose_root_nearest_60pct",
                "frozen_after_calibration": True,
            },
        },
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
            "oos_drawdown_floor": -0.22,
            "oos_sharpe_min": 0.80,
            "oos_calmar_min": 0.50,
            "return_lift_vs_risk_control_min": 0.01,
            "sharpe_lift_vs_risk_control_min": 0.10,
            "drawdown_worse_vs_risk_control_max": 0.02,
            "volatility_worse_vs_risk_control_max": 0.015,
            "volatility_reduction_vs_direct_min": 0.15,
            "drawdown_improvement_vs_direct_min": 0.05,
            "return_shortfall_vs_direct_max": 0.03,
            "all_three_folds_positive": True,
            "worst_fold_drawdown_floor": -0.22,
            "median_fold_sharpe_min": 0.65,
            "locked_return_min": 0.10,
            "locked_drawdown_floor": -0.20,
            "locked_sharpe_min": 0.80,
            "positive_years_min": 6,
            "annual_turnover_max": 1.0,
            "stress_return_lift_vs_risk_control_min": 0.007,
            "stress_sharpe_min": 0.75,
            "worst_day_floor": -0.08,
            "expected_shortfall_95_floor": -0.025,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "oos_opportunity_cost_risk_matched_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先冻结候选、校准公式和机会成本闸门，再读取完整行情。"""
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
    calibration = calibrate_risk_control(panel.adjusted_close)
    risk_control_weights = {
        SP500: calibration["risk_control_sp500_weight"],
        BOND: calibration["risk_control_bond_weight"],
    }
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(CALIBRATION_START)
    ]
    target_sets = {
        EXPERIMENT_ID: global_study._build_targets(
            signals,
            CANDIDATE_WEIGHTS,
        ),
        NOMINAL_CONTROL_ID: global_study._build_targets(
            signals,
            NOMINAL_CONTROL_WEIGHTS,
        ),
        RISK_CONTROL_ID: global_study._build_targets(
            signals,
            risk_control_weights,
        ),
        DIRECT_ID: global_study._build_targets(signals, {SP500: 1.0}),
    }
    benchmark = global_study._benchmark_curve(panel)
    base_model = ExecutionModel(stamp_tax_rate=0.0, slippage_bps=5.0)
    runs = {
        strategy_id: run_risk_layer_backtest(
            strategy_id,
            "FIXED",
            targets,
            panel.bars,
            panel.calendar,
            benchmark,
            base_model,
        )
        for strategy_id, targets in target_sets.items()
    }
    stress_targets = target_sets[EXPERIMENT_ID]
    runs[STRESS_ID] = run_risk_layer_backtest(
        STRESS_ID,
        "FIXED",
        stress_targets,
        panel.bars,
        panel.calendar,
        benchmark,
        ExecutionModel(stamp_tax_rate=0.0, slippage_bps=20.0),
    )
    target_sets[STRESS_ID] = stress_targets
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
    diagnostics = build_diagnostics(paths, runs, calibration)
    gate = evaluate_gate(metrics, annual, diagnostics)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "calibration": calibration,
        "period_metrics": metrics[EXPERIMENT_ID],
        "period_comparison": metrics,
        "annual_comparison": annual,
        "diagnostics": diagnostics,
        "gate": gate,
        "latest_holdings": [
            {
                "signal_date": max(target_sets[EXPERIMENT_ID]),
                "symbol": symbol,
                "target_weight": weight,
            }
            for symbol, weight in CANDIDATE_WEIGHTS.items()
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


def calibrate_risk_control(
    adjusted_close: pd.DataFrame,
) -> dict[str, float]:
    """只用校准期协方差闭式求解标普/国债同波动权重。"""
    returns = (
        adjusted_close[[SP500, GOLD, BOND]]
        .loc[CALIBRATION_START:CALIBRATION_END]
        .pct_change(fill_method=None)
        .dropna()
    )
    if len(returns) < 1000:
        raise ValueError("risk calibration requires at least 1000 returns")
    candidate = (
        CANDIDATE_WEIGHTS[SP500] * returns[SP500]
        + CANDIDATE_WEIGHTS[GOLD] * returns[GOLD]
    )
    target_variance = float(candidate.var(ddof=1))
    sp_variance = float(returns[SP500].var(ddof=1))
    bond_variance = float(returns[BOND].var(ddof=1))
    covariance = float(returns[[SP500, BOND]].cov().iloc[0, 1])
    coefficients = [
        sp_variance + bond_variance - 2.0 * covariance,
        2.0 * (covariance - bond_variance),
        bond_variance - target_variance,
    ]
    roots = np.roots(coefficients)
    valid = [
        float(root.real)
        for root in roots
        if abs(float(root.imag)) < 1e-10 and 0.0 <= float(root.real) <= 1.0
    ]
    if not valid:
        raise ValueError(f"no feasible risk matched control weight: {roots}")
    sp_weight = min(valid, key=lambda value: abs(value - 0.60))
    control = sp_weight * returns[SP500] + (1.0 - sp_weight) * returns[BOND]
    return {
        "candidate_volatility": float(candidate.std(ddof=1) * math.sqrt(252)),
        "risk_control_sp500_weight": sp_weight,
        "risk_control_bond_weight": 1.0 - sp_weight,
        "risk_control_volatility": float(
            control.std(ddof=1) * math.sqrt(252)
        ),
        "calibration_observations": int(len(returns)),
    }


def build_diagnostics(
    paths: RuntimePaths,
    runs: dict[str, RiskLayerRun],
    calibration: dict[str, float],
) -> dict[str, Any]:
    """计算评价期真实风险、尾部和对现有Quality独立性。"""
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
    return {
        **calibration,
        "candidate_volatility": _annualized_volatility(navs[EXPERIMENT_ID]),
        "direct_sp500_volatility": _annualized_volatility(navs[DIRECT_ID]),
        "risk_control_volatility": _annualized_volatility(
            navs[RISK_CONTROL_ID]
        ),
        "nominal_control_volatility": _annualized_volatility(
            navs[NOMINAL_CONTROL_ID]
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
    """机会成本、风险匹配、成本和尾部门槛必须全部通过。"""
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["oos_full"]
    locked = candidate["locked_test"]
    risk_control = metrics[RISK_CONTROL_ID]["oos_full"]
    direct = metrics[DIRECT_ID]["oos_full"]
    stress = metrics[STRESS_ID]["oos_full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    return_lift_risk = (
        full["annualized_return"] - risk_control["annualized_return"]
    )
    sharpe_lift_risk = full["sharpe"] - risk_control["sharpe"]
    drawdown_gap_risk = (
        abs(full["max_drawdown"]) - abs(risk_control["max_drawdown"])
    )
    return_lift_direct = (
        full["annualized_return"] - direct["annualized_return"]
    )
    volatility_reduction = 1.0 - (
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
        "oos_drawdown_within_22pct": full["max_drawdown"] >= -0.22,
        "oos_sharpe_at_least_080": full["sharpe"] >= 0.80,
        "oos_calmar_at_least_050": full["calmar"] >= 0.50,
        "return_lift_vs_risk_control_at_least_1pct": (
            return_lift_risk >= 0.01
        ),
        "sharpe_lift_vs_risk_control_at_least_010": (
            sharpe_lift_risk >= 0.10
        ),
        "drawdown_worse_vs_risk_control_within_2pct": (
            drawdown_gap_risk <= 0.02
        ),
        "volatility_worse_vs_risk_control_within_15pct": (
            diagnostics["candidate_volatility"]
            <= diagnostics["risk_control_volatility"] + 0.015
        ),
        "volatility_reduction_vs_direct_at_least_15pct": (
            volatility_reduction >= 0.15
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
        "worst_fold_drawdown_within_22pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.22,
        "median_fold_sharpe_at_least_065": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.65,
        "locked_return_at_least_10pct": (
            locked["annualized_return"] >= 0.10
        ),
        "locked_drawdown_within_20pct": (
            locked["max_drawdown"] >= -0.20
        ),
        "locked_sharpe_at_least_080": locked["sharpe"] >= 0.80,
        "at_least_six_positive_years": positive_years >= 6,
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "stress_return_lift_vs_risk_control_at_least_07pct": (
            stress["annualized_return"]
            - risk_control["annualized_return"]
            >= 0.007
        ),
        "stress_sharpe_at_least_075": stress["sharpe"] >= 0.75,
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
        "return_lift_vs_risk_control": return_lift_risk,
        "sharpe_lift_vs_risk_control": sharpe_lift_risk,
        "drawdown_gap_vs_risk_control": drawdown_gap_risk,
        "return_lift_vs_direct_sp500": return_lift_direct,
        "volatility_reduction_vs_direct_sp500": volatility_reduction,
        "drawdown_improvement_vs_direct_sp500": (
            drawdown_improvement_direct
        ),
        "positive_years": positive_years,
    }


def build_decision_reason(gate: dict[str, Any]) -> str:
    """完整记录机会成本闸门的实际失败项。"""
    if gate["passed"]:
        return "60/40候选通过全部机会成本门槛，仅允许前向Paper"
    failed = [name for name, passed in gate["checks"].items() if not passed]
    return f"60/40候选未通过机会成本门槛（{', '.join(failed)}），归档且不注册"


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, dict[str, float]]],
    diagnostics: dict[str, Any],
) -> None:
    """保存全部对照净值、冻结目标和诊断。"""
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
            ExperimentArtifact("summary", summary_path, "机会成本研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与简单对照净值"),
            ExperimentArtifact("monthly_targets", targets_path, "全部月度目标"),
            ExperimentArtifact("annual_metrics", annual_path, "年度机会成本比较"),
            ExperimentArtifact(
                "diagnostics",
                diagnostics_path,
                "校准、波动率、尾部和相关性诊断",
            ),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定基金历史、增量和Quality监控事实版本。"""
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
