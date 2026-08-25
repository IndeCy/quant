"""纳指50%、黄金25%、国债25%固定平衡组合的独立多折研究。"""

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
from data.fund_portfolio import FundPortfolioPanel, load_fund_portfolio_panel
from examples import global_defensive_equal_study as global_study
from examples.nasdaq_gold_bond_balanced_report import render_report
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
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


EXPERIMENT_ID = "nasdaq_gold_bond_balanced_50_25_25_v1"
REPORT_PATH = Path("docs/research/nasdaq-gold-bond-balanced-50-25-25-v1.md")
NASDAQ = "159941.SZ"
GOLD = "518880.SH"
BOND = "511010.SH"
SP500 = "513500.SH"
BENCHMARK = "510300.SH"
WEIGHTS = {NASDAQ: 0.50, GOLD: 0.25, BOND: 0.25}
NASDAQ_GOLD_WEIGHTS = {NASDAQ: 0.60, GOLD: 0.40}
GLOBAL_WEIGHTS = {SP500: 1 / 3, GOLD: 1 / 3, BOND: 1 / 3}
LOAD_START = "20150713"
STUDY_START = "20160101"
LOCKED_START = "20240101"
RELIABLE_AS_OF = "20260728"
NASDAQ_GOLD_ID = "nasdaq_gold_60_40_balanced_control"
GLOBAL_ID = "global_defensive_balanced_control"
SP500_ID = "sp500_direct_balanced_control"
STRESS_ID = "nasdaq_gold_bond_balanced_cost_20bps"
FOLD_KEYS = ("2016_2018", "2019_2021", "2022_2023", "2024_latest")
PERIODS = {
    "2016_2018": ("20160101", "20181231"),
    "2019_2021": ("20190101", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
    "locked_test": (LOCKED_START, "LATEST"),
    "full": (STUDY_START, "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指50×黄金25×国债25增长防守平衡 V1",
    category="allocation_strategy",
    hypothesis=(
        "用一半纳指增长和各四分之一人民币黄金、五年国债构成固定增长防守平衡，"
        "能否在保留纳指黄金60/40大部分收益的同时降低回撤，并继续清除场内标普机会成本"
    ),
    definition={
        "assets": {
            "growth": NASDAQ,
            "real_defense": GOLD,
            "nominal_defense": BOND,
            "weights": WEIGHTS,
        },
        "portfolio": {
            "rebalance": "monthly",
            "weight_grid": False,
            "timing": False,
            "leverage": 1.0,
        },
        "controls": {
            "nasdaq_gold_60_40": NASDAQ_GOLD_WEIGHTS,
            "global_defensive_equal": GLOBAL_WEIGHTS,
            "sp500_direct": {SP500: 1.0},
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
            "stamp_tax_rate": 0.0,
        },
        "evaluation": {
            "periods": PERIODS,
            "full_return_min": 0.10,
            "full_drawdown_floor": -0.20,
            "full_sharpe_min": 1.00,
            "full_calmar_min": 0.55,
            "return_lift_vs_sp500_min": 0.005,
            "return_shortfall_vs_nasdaq_gold_max": 0.035,
            "drawdown_improvement_vs_nasdaq_gold_min": 0.02,
            "sharpe_lift_vs_nasdaq_gold_min": 0.00,
            "return_at_least_global": True,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.22,
            "median_fold_sharpe_min": 0.75,
            "locked_return_min": 0.09,
            "locked_drawdown_floor": -0.18,
            "locked_sharpe_min": 0.80,
            "positive_years_min": 8,
            "annual_turnover_max": 1.0,
            "stress_return_min": 0.09,
            "stress_sharpe_min": 0.85,
            "worst_day_floor": -0.07,
            "expected_shortfall_95_floor": -0.025,
            "quality_correlation_max": 0.35,
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "growth_defense_50_25_25_multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
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
        result, runs, targets = _calculate(paths, normalized_as_of)
        _complete_attempt(attempt, result, runs, targets)
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
]:
    symbols = [NASDAQ, GOLD, BOND, SP500, BENCHMARK]
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        symbols,
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    audit = audit_panel(panel, symbols, as_of_date)
    if not audit["passed"]:
        raise ValueError(f"growth-defense panel audit failed: {audit}")
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    target_sets = {
        EXPERIMENT_ID: _fixed_targets(signals, WEIGHTS),
        NASDAQ_GOLD_ID: _fixed_targets(signals, NASDAQ_GOLD_WEIGHTS),
        GLOBAL_ID: _fixed_targets(signals, GLOBAL_WEIGHTS),
        SP500_ID: _fixed_targets(signals, {SP500: 1.0}),
    }
    target_sets[STRESS_ID] = target_sets[EXPERIMENT_ID]
    benchmark = _benchmark_curve(panel)
    runs = {
        strategy_id: _run(
            strategy_id,
            targets,
            panel,
            benchmark,
            slippage_bps=20.0 if strategy_id == STRESS_ID else 5.0,
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
    annual_all = build_annual_metrics(runs, benchmark, panel.latest_common_date)
    annual = {
        year: item
        for year, item in annual_all[EXPERIMENT_ID].items()
        if year >= STUDY_START[:4]
    }
    diagnostics = build_diagnostics(paths, runs[EXPERIMENT_ID])
    gate = evaluate_gate(metrics, annual, diagnostics, audit)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "data_audit": audit,
        "period_metrics": metrics[EXPERIMENT_ID],
        "full_comparison": {
            name: values["full"]
            for name, values in metrics.items()
            if name != STRESS_ID
        },
        "annual_metrics": annual,
        "diagnostics": diagnostics,
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, target_sets


def build_diagnostics(
    paths: RuntimePaths,
    run: RiskLayerRun,
) -> dict[str, float | int]:
    nav = run.result.daily_values.loc[STUDY_START:].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    drawdown = nav / nav.cummax() - 1.0
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift(fill_value=False)).cumsum()
    lengths = underwater.groupby(groups).sum()
    return {
        "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)),
        "worst_day": float(returns.min()),
        "expected_shortfall_95": float(returns[returns.le(threshold)].mean()),
        "max_underwater_days": int(lengths.max()) if len(lengths) else 0,
        "quality_correlation": global_study.load_quality_correlation(paths, run),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, float]],
    diagnostics: dict[str, float | int],
    audit: dict[str, Any],
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    nasdaq_gold = metrics[NASDAQ_GOLD_ID]["full"]
    global_equal = metrics[GLOBAL_ID]["full"]
    sp500 = metrics[SP500_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    checks = {
        "data_audit": bool(audit["passed"]),
        "full_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_20pct": full["max_drawdown"] >= -0.20,
        "full_sharpe_at_least_100": full["sharpe"] >= 1.00,
        "full_calmar_at_least_055": full["calmar"] >= 0.55,
        "return_lift_vs_sp500_at_least_05pct": (
            full["annualized_return"] - sp500["annualized_return"] >= 0.005
        ),
        "return_shortfall_vs_nasdaq_gold_within_35pct": (
            nasdaq_gold["annualized_return"] - full["annualized_return"] <= 0.035
        ),
        "drawdown_improvement_vs_nasdaq_gold_at_least_2pct": (
            abs(nasdaq_gold["max_drawdown"]) - abs(full["max_drawdown"]) >= 0.02
        ),
        "sharpe_at_least_nasdaq_gold": full["sharpe"] >= nasdaq_gold["sharpe"],
        "return_at_least_global_equal": (
            full["annualized_return"] >= global_equal["annualized_return"]
        ),
        "all_four_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_22pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.22,
        "median_fold_sharpe_at_least_075": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.75,
        "locked_return_at_least_9pct": locked["annualized_return"] >= 0.09,
        "locked_drawdown_within_18pct": locked["max_drawdown"] >= -0.18,
        "locked_sharpe_at_least_080": locked["sharpe"] >= 0.80,
        "at_least_eight_positive_years": positive_years >= 8,
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "stress_return_at_least_9pct": stress["annualized_return"] >= 0.09,
        "stress_sharpe_at_least_085": stress["sharpe"] >= 0.85,
        "worst_day_within_7pct": float(diagnostics["worst_day"]) >= -0.07,
        "expected_shortfall_95_within_25pct": (
            float(diagnostics["expected_shortfall_95"]) >= -0.025
        ),
        "quality_correlation_at_most_035": (
            abs(float(diagnostics["quality_correlation"])) <= 0.35
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
    }


def audit_panel(
    panel: FundPortfolioPanel,
    symbols: list[str],
    as_of_date: str,
) -> dict[str, Any]:
    covered = {str(item["symbol"]) for item in panel.coverage}
    lag = (pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)).days
    checks = {
        "all_assets_present": covered == set(symbols),
        "latest_within_five_days": 0 <= lag <= 5,
        "at_least_2600_common_days": len(panel.calendar) >= 2600,
        "all_assets_start_before_2016": all(
            str(item["start_date"]) < STUDY_START
            for item in panel.coverage
        ),
        "no_duplicate_dates": not panel.adjusted_close.index.duplicated().any(),
        "all_prices_positive": bool(panel.adjusted_close.gt(0).all().all()),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "latest_common_date": panel.latest_common_date,
        "common_days": len(panel.calendar),
    }


def _fixed_targets(
    signals: list[pd.Timestamp],
    weights: dict[str, float],
) -> dict[str, dict[str, float]]:
    return {
        date.strftime("%Y%m%d"): dict(weights)
        for date in signals
    }


def _run(
    name: str,
    targets: dict[str, dict[str, float]],
    panel: FundPortfolioPanel,
    benchmark: pd.Series,
    *,
    slippage_bps: float,
) -> RiskLayerRun:
    return run_risk_layer_backtest(
        name,
        "FIXED",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        ExecutionModel(
            stamp_tax_rate=0.0,
            slippage_bps=slippage_bps,
        ),
    )


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    values = panel.adjusted_close[BENCHMARK].astype(float)
    return values / float(values.iloc[0])


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, dict[str, float]]],
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
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
    diagnostics_path = attempt.output_dir / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(
            {
                "data_audit": result["data_audit"],
                "diagnostics": result["diagnostics"],
                "gate": result["gate"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    series_rows = []
    for series_id, series_name in [
        (EXPERIMENT_ID, "纳指50黄金25国债25"),
        (NASDAQ_GOLD_ID, "纳指黄金60/40"),
        (SP500_ID, "标普500ETF"),
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
            if date >= pd.Timestamp(STUDY_START)
        )
    SystemRepository(attempt.paths.system_state_path).replace_experiment_series(
        attempt.run_id,
        attempt.spec.experiment_id,
        series_rows,
    )
    passed = bool(result["gate"]["passed"])
    failed = [
        name
        for name, value in result["gate"]["checks"].items()
        if not value
    ]
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "纳指黄金国债增长防守平衡通过冻结门槛，仅允许前向研究观察"
            if passed
            else f"纳指黄金国债增长防守平衡未通过门槛（{', '.join(failed)}），归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "增长防守平衡研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("monthly_targets", targets_path, "月度目标"),
            ExperimentArtifact("diagnostics", diagnostics_path, "尾部与门槛诊断"),
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
    parser.add_argument("--as-of-date", default=RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
