"""境内纳指100与黄金固定60/40相对标普500的硬门槛研究。"""

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
from examples.nasdaq_gold_sp500_hurdle_report import render_report
from factors.etf_momentum import month_end_signal_dates
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


EXPERIMENT_ID = "nasdaq_gold_60_40_sp500_hurdle_v3"
REPORT_PATH = Path("docs/research/nasdaq-gold-60-40-sp500-hurdle-v3.md")
NASDAQ = "159941.SZ"
GOLD = "518880.SH"
SP500 = "513500.SH"
BOND = "511010.SH"
BENCHMARK = "510300.SH"
RELIABLE_AS_OF = "20260728"
CANDIDATE_WEIGHTS = {NASDAQ: 0.60, GOLD: 0.40}
CALIBRATION_START = "20150713"
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
RISK_CONTROL_ID = "sp500_bond_nasdaq_calibration_risk_control"
SP500_DIRECT_ID = "sp500_direct_nasdaq_hurdle_control"
NASDAQ_DIRECT_ID = "nasdaq_direct_control"
STRESS_ID = "nasdaq_gold_60_40_sp500_hurdle_cost_20bps"

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="境内纳指100 × 黄金固定60/40相对标普500硬门槛 V3",
    category="allocation_strategy",
    hypothesis=(
        "境内纳指增长暴露与人民币黄金固定60/40，能否在不承担高于"
        "直接标普500风险的前提下，产生至少1个百分点净收益优势"
    ),
    definition={
        "candidate": {
            "assets": CANDIDATE_WEIGHTS,
            "weight_grid": False,
            "rebalance": "monthly",
        },
        "hard_opportunity_cost": {SP500: 1.0},
        "source_risk_control": {NASDAQ: 1.0},
        "risk_matched_simple_control": {
            "assets": [SP500, BOND],
            "calibration_period": [CALIBRATION_START, CALIBRATION_END],
            "target": "candidate_daily_return_volatility",
            "solver": "closed_form_quadratic_choose_root_nearest_60pct",
            "frozen_after_calibration": True,
            "promotion_role": (
                "diagnostic_when_candidate_directly_dominates_sp500;"
                "required_only_for_lower_return_candidate"
            ),
        },
        "data_policy": {
            "reliable_common_as_of": RELIABLE_AS_OF,
            "no_forward_fill_after_source_end": True,
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
            "data_common_days_min": 2600,
            "oos_return_min": 0.12,
            "oos_drawdown_floor": -0.25,
            "oos_sharpe_min": 0.90,
            "oos_calmar_min": 0.50,
            "return_lift_vs_direct_sp500_min": 0.01,
            "sharpe_lift_vs_direct_sp500_min": 0.10,
            "volatility_worse_vs_direct_sp500_max": 0.01,
            "drawdown_worse_vs_direct_sp500_max": 0.02,
            "direct_nasdaq_return_shortfall_max": 0.05,
            "direct_nasdaq_drawdown_improvement_min": 0.08,
            "all_three_folds_positive": True,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.70,
            "locked_return_min": 0.12,
            "locked_drawdown_floor": -0.23,
            "locked_sharpe_min": 0.85,
            "positive_years_min": 6,
            "annual_turnover_max": 1.0,
            "stress_return_lift_vs_direct_sp500_min": 0.007,
            "stress_sharpe_min": 0.85,
            "worst_day_floor": -0.09,
            "expected_shortfall_95_floor": -0.03,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "direct_sp500_dominance_oos_v3",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """冻结直接标普硬门槛后再读取完整行情。"""
    normalized_as_of = min(str(as_of_date).replace("-", ""), RELIABLE_AS_OF)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized_as_of,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, runs, targets, diagnostics = _calculate(
            paths,
            normalized_as_of,
        )
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
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [NASDAQ, GOLD, SP500, BOND, BENCHMARK],
        start_date=CALIBRATION_START,
        end_date=as_of_date,
    )
    audit = audit_panel(panel)
    if not audit["passed"]:
        raise ValueError(f"fund panel audit failed: {audit}")
    calibration = calibrate_risk_control(panel.adjusted_close)
    risk_control_weights = {
        SP500: calibration["risk_control_sp500_weight"],
        BOND: calibration["risk_control_bond_weight"],
    }
    signals = month_end_signal_dates(panel.calendar)
    target_sets = {
        EXPERIMENT_ID: global_study._build_targets(
            signals,
            CANDIDATE_WEIGHTS,
        ),
        RISK_CONTROL_ID: global_study._build_targets(
            signals,
            risk_control_weights,
        ),
        SP500_DIRECT_ID: global_study._build_targets(
            signals,
            {SP500: 1.0},
        ),
        NASDAQ_DIRECT_ID: global_study._build_targets(
            signals,
            {NASDAQ: 1.0},
        ),
    }
    target_sets[STRESS_ID] = target_sets[EXPERIMENT_ID]
    benchmark = global_study._benchmark_curve(panel)
    runs = {
        strategy_id: run_risk_layer_backtest(
            strategy_id,
            "FIXED",
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
    diagnostics = build_diagnostics(paths, runs)
    gate = evaluate_gate(metrics, annual, diagnostics, audit)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "data_audit": audit,
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


def audit_panel(panel: FundPortfolioPanel) -> dict[str, Any]:
    """确认所有境内ETF覆盖完整、截止一致且不含非法价格。"""
    coverage = {str(item["symbol"]): item for item in panel.coverage}
    expected = {NASDAQ, GOLD, SP500, BOND, BENCHMARK}
    checks = {
        "all_symbols_present": set(coverage) == expected,
        "common_end_is_reliable_as_of": panel.latest_common_date == RELIABLE_AS_OF,
        "at_least_2600_common_days": len(panel.calendar) >= 2600,
        "no_missing_adjusted_close": not panel.adjusted_close.isna().any().any(),
        "positive_adjusted_close": bool(
            panel.adjusted_close.gt(0).all().all()
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "common_start": panel.calendar[0].strftime("%Y%m%d"),
        "common_end": panel.latest_common_date,
        "common_days": len(panel.calendar),
        "coverage": panel.coverage,
    }


def calibrate_risk_control(
    adjusted_close: pd.DataFrame,
) -> dict[str, float]:
    """用校准期协方差闭式冻结标普500/国债同波动权重。"""
    returns = (
        adjusted_close[[NASDAQ, GOLD, SP500, BOND]]
        .loc[CALIBRATION_START:CALIBRATION_END]
        .pct_change(fill_method=None)
        .dropna()
    )
    if len(returns) < 750:
        raise ValueError("risk calibration requires at least 750 returns")
    candidate = (
        CANDIDATE_WEIGHTS[NASDAQ] * returns[NASDAQ]
        + CANDIDATE_WEIGHTS[GOLD] * returns[GOLD]
    )
    target_variance = float(candidate.var(ddof=1))
    sp_variance = float(returns[SP500].var(ddof=1))
    bond_variance = float(returns[BOND].var(ddof=1))
    covariance = float(returns[[SP500, BOND]].cov().iloc[0, 1])
    roots = np.roots(
        [
            sp_variance + bond_variance - 2.0 * covariance,
            2.0 * (covariance - bond_variance),
            bond_variance - target_variance,
        ]
    )
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
) -> dict[str, Any]:
    """计算评价期真实风险、尾部与Quality相关性。"""
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
        "candidate_volatility": _annualized_volatility(
            navs[EXPERIMENT_ID]
        ),
        "risk_control_volatility": _annualized_volatility(
            navs[RISK_CONTROL_ID]
        ),
        "direct_sp500_volatility": _annualized_volatility(
            navs[SP500_DIRECT_ID]
        ),
        "direct_nasdaq_volatility": _annualized_volatility(
            navs[NASDAQ_DIRECT_ID]
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
    audit: dict[str, Any],
) -> dict[str, Any]:
    """候选直接支配标普时，以直接机会成本为晋级硬门槛。"""
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["oos_full"]
    locked = candidate["locked_test"]
    risk_control = metrics[RISK_CONTROL_ID]["oos_full"]
    sp500 = metrics[SP500_DIRECT_ID]["oos_full"]
    nasdaq = metrics[NASDAQ_DIRECT_ID]["oos_full"]
    stress = metrics[STRESS_ID]["oos_full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    return_lift_sp500 = (
        full["annualized_return"] - sp500["annualized_return"]
    )
    sharpe_lift_sp500 = full["sharpe"] - sp500["sharpe"]
    volatility_gap_sp500 = (
        diagnostics["candidate_volatility"]
        - diagnostics["direct_sp500_volatility"]
    )
    drawdown_gap_sp500 = (
        abs(full["max_drawdown"]) - abs(sp500["max_drawdown"])
    )
    return_lift_risk = (
        full["annualized_return"] - risk_control["annualized_return"]
    )
    sharpe_lift_risk = full["sharpe"] - risk_control["sharpe"]
    volatility_gap_risk = (
        diagnostics["candidate_volatility"]
        - diagnostics["risk_control_volatility"]
    )
    return_lift_nasdaq = (
        full["annualized_return"] - nasdaq["annualized_return"]
    )
    drawdown_improvement_nasdaq = (
        full["max_drawdown"] - nasdaq["max_drawdown"]
    )
    positive_years = sum(
        item["annualized_return"] > 0
        for item in annual[EXPERIMENT_ID].values()
    )
    checks = {
        "data_audit": bool(audit["passed"]),
        "oos_annual_return_at_least_12pct": (
            full["annualized_return"] >= 0.12
        ),
        "oos_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "oos_sharpe_at_least_090": full["sharpe"] >= 0.90,
        "oos_calmar_at_least_050": full["calmar"] >= 0.50,
        "return_lift_vs_direct_sp500_at_least_1pct": (
            return_lift_sp500 >= 0.01
        ),
        "sharpe_lift_vs_direct_sp500_at_least_010": (
            sharpe_lift_sp500 >= 0.10
        ),
        "volatility_worse_vs_direct_sp500_within_1pct": (
            volatility_gap_sp500 <= 0.01
        ),
        "drawdown_worse_vs_direct_sp500_within_2pct": (
            drawdown_gap_sp500 <= 0.02
        ),
        "return_shortfall_vs_direct_nasdaq_within_5pct": (
            return_lift_nasdaq >= -0.05
        ),
        "drawdown_improvement_vs_direct_nasdaq_at_least_8pct": (
            drawdown_improvement_nasdaq >= 0.08
        ),
        "all_three_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_25pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.25,
        "median_fold_sharpe_at_least_070": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.70,
        "locked_return_at_least_12pct": (
            locked["annualized_return"] >= 0.12
        ),
        "locked_drawdown_within_23pct": (
            locked["max_drawdown"] >= -0.23
        ),
        "locked_sharpe_at_least_085": locked["sharpe"] >= 0.85,
        "at_least_six_positive_years": positive_years >= 6,
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "stress_return_lift_vs_direct_sp500_at_least_07pct": (
            stress["annualized_return"]
            - sp500["annualized_return"]
            >= 0.007
        ),
        "stress_sharpe_at_least_085": stress["sharpe"] >= 0.85,
        "worst_day_within_9pct": diagnostics["worst_day"] >= -0.09,
        "expected_shortfall_95_within_3pct": (
            diagnostics["expected_shortfall_95"] >= -0.03
        ),
        "quality_correlation_at_most_050": (
            abs(diagnostics["quality_correlation"]) <= 0.50
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "return_lift_vs_direct_sp500": return_lift_sp500,
        "sharpe_lift_vs_direct_sp500": sharpe_lift_sp500,
        "volatility_gap_vs_direct_sp500": volatility_gap_sp500,
        "drawdown_gap_vs_direct_sp500": drawdown_gap_sp500,
        "return_lift_vs_risk_control": return_lift_risk,
        "sharpe_lift_vs_risk_control": sharpe_lift_risk,
        "volatility_gap_vs_risk_control": volatility_gap_risk,
        "return_lift_vs_direct_nasdaq": return_lift_nasdaq,
        "drawdown_improvement_vs_direct_nasdaq": (
            drawdown_improvement_nasdaq
        ),
        "positive_years": positive_years,
    }


def build_decision_reason(gate: dict[str, Any]) -> str:
    """保留全部实际失败的硬门槛。"""
    if gate["passed"]:
        return "纳指黄金60/40通过直接标普硬门槛，仅允许前向Paper"
    failed = [name for name, passed in gate["checks"].items() if not passed]
    return f"纳指黄金60/40未通过硬门槛（{', '.join(failed)}），归档且不注册"


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, dict[str, float]]],
    diagnostics: dict[str, Any],
) -> None:
    """保存全部净值、目标、年度和诊断。"""
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
        json.dumps(
            {
                "data_audit": result["data_audit"],
                "calibration": result["calibration"],
                **diagnostics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    series_rows = []
    for series_id, series_name in [
        (EXPERIMENT_ID, "纳指黄金60/40（V3）"),
        (SP500_DIRECT_ID, "标普500ETF（513500）"),
    ]:
        nav = runs[series_id].result.daily_values.astype(float)
        normalized = nav / float(nav.iloc[0])
        series_rows.extend(
            {
                "series_id": series_id,
                "series_name": series_name,
                "trade_date": date.strftime("%Y%m%d"),
                "nav": float(value),
                "adjust_policy": "qfq_m0_t1_5bps",
            }
            for date, value in normalized.items()
        )
    SystemRepository(attempt.paths.system_state_path).replace_experiment_series(
        attempt.run_id,
        attempt.spec.experiment_id,
        series_rows,
    )
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=build_decision_reason(result["gate"]),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "直接标普硬门槛报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与三类对照净值"),
            ExperimentArtifact("monthly_targets", targets_path, "完整月度目标"),
            ExperimentArtifact("annual_metrics", annual_path, "年度机会成本比较"),
            ExperimentArtifact(
                "diagnostics",
                diagnostics_path,
                "数据、校准、尾部和相关性诊断",
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
    parser.add_argument("--as-of-date", default=RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
