"""A股科技、红利低波与黄金ETF固定等权的独立多折研究。"""

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
from examples.china_tech_dividend_gold_report import render_report
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


EXPERIMENT_ID = "china_tech_dividend_gold_equal_v1"
REPORT_PATH = Path("docs/research/china-tech-dividend-gold-equal-v1.md")
TECH = "515000.SH"
DIVIDEND = "512890.SH"
GOLD = "518880.SH"
SP500 = "513500.SH"
NASDAQ = "159941.SZ"
BENCHMARK = "510300.SH"
WEIGHTS = {TECH: 1 / 3, DIVIDEND: 1 / 3, GOLD: 1 / 3}
TECH_DIVIDEND_WEIGHTS = {TECH: 0.50, DIVIDEND: 0.50}
NASDAQ_GOLD_WEIGHTS = {NASDAQ: 0.60, GOLD: 0.40}
LOAD_START = "20190816"
STUDY_START = "20200101"
LOCKED_START = "20240101"
RELIABLE_AS_OF = "20260728"
TECH_DIVIDEND_ID = "china_tech_dividend_50_50_control"
TECH_ID = "china_tech_direct_control"
SP500_ID = "sp500_direct_china_barbell_control"
NASDAQ_GOLD_ID = "nasdaq_gold_60_40_china_barbell_control"
STRESS_ID = "china_tech_dividend_gold_cost_20bps"
FOLD_KEYS = ("2020_2021", "2022_2023", "2024_latest")
PERIODS = {
    "2020_2021": ("20200101", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
    "locked_test": (LOCKED_START, "LATEST"),
    "full": (STUDY_START, "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="A股科技×红利低波×黄金固定等权 V1",
    category="allocation_strategy",
    hypothesis=(
        "A股科技成长与红利低波的风格互补叠加人民币黄金，能否在完全不择时的条件下，"
        "同时改善国内科技单持的尾部风险并清除场内标普500机会成本"
    ),
    definition={
        "assets": {
            "china_growth": TECH,
            "china_value": DIVIDEND,
            "real_asset": GOLD,
            "weights": WEIGHTS,
        },
        "portfolio": {
            "rebalance": "monthly",
            "weight_grid": False,
            "timing": False,
            "ranking": False,
            "leverage": 1.0,
        },
        "controls": {
            "china_tech_dividend_50_50": TECH_DIVIDEND_WEIGHTS,
            "china_tech_direct": {TECH: 1.0},
            "sp500_direct": {SP500: 1.0},
            "nasdaq_gold_60_40": NASDAQ_GOLD_WEIGHTS,
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
            "full_drawdown_floor": -0.28,
            "full_sharpe_min": 0.75,
            "full_calmar_min": 0.40,
            "return_lift_vs_sp500_min": 0.005,
            "sharpe_lift_vs_tech_dividend_min": 0.10,
            "drawdown_improvement_vs_tech_dividend_min": 0.05,
            "drawdown_improvement_vs_tech_min": 0.15,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.30,
            "median_fold_sharpe_min": 0.55,
            "locked_return_min": 0.10,
            "locked_drawdown_floor": -0.22,
            "locked_sharpe_min": 0.70,
            "positive_years_min": 5,
            "annual_turnover_max": 1.0,
            "stress_return_min": 0.09,
            "stress_sharpe_min": 0.65,
            "worst_day_floor": -0.08,
            "expected_shortfall_95_floor": -0.035,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "china_three_style_equal_multifold_v1",
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
    symbols = [TECH, DIVIDEND, GOLD, SP500, NASDAQ, BENCHMARK]
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        symbols,
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    audit = audit_panel(panel, symbols, as_of_date)
    if not audit["passed"]:
        raise ValueError(f"china three-style panel audit failed: {audit}")
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    target_sets = {
        EXPERIMENT_ID: _fixed_targets(signals, WEIGHTS),
        TECH_DIVIDEND_ID: _fixed_targets(signals, TECH_DIVIDEND_WEIGHTS),
        TECH_ID: _fixed_targets(signals, {TECH: 1.0}),
        SP500_ID: _fixed_targets(signals, {SP500: 1.0}),
        NASDAQ_GOLD_ID: _fixed_targets(signals, NASDAQ_GOLD_WEIGHTS),
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
    tech_dividend = metrics[TECH_DIVIDEND_ID]["full"]
    tech = metrics[TECH_ID]["full"]
    sp500 = metrics[SP500_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    checks = {
        "data_audit": bool(audit["passed"]),
        "full_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_28pct": full["max_drawdown"] >= -0.28,
        "full_sharpe_at_least_075": full["sharpe"] >= 0.75,
        "full_calmar_at_least_040": full["calmar"] >= 0.40,
        "return_lift_vs_sp500_at_least_05pct": (
            full["annualized_return"] - sp500["annualized_return"] >= 0.005
        ),
        "sharpe_lift_vs_tech_dividend_at_least_010": (
            full["sharpe"] - tech_dividend["sharpe"] >= 0.10
        ),
        "drawdown_improvement_vs_tech_dividend_at_least_5pct": (
            abs(tech_dividend["max_drawdown"]) - abs(full["max_drawdown"]) >= 0.05
        ),
        "drawdown_improvement_vs_tech_at_least_15pct": (
            abs(tech["max_drawdown"]) - abs(full["max_drawdown"]) >= 0.15
        ),
        "all_three_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_30pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.30,
        "median_fold_sharpe_at_least_055": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.55,
        "locked_return_at_least_10pct": locked["annualized_return"] >= 0.10,
        "locked_drawdown_within_22pct": locked["max_drawdown"] >= -0.22,
        "locked_sharpe_at_least_070": locked["sharpe"] >= 0.70,
        "at_least_five_positive_years": positive_years >= 5,
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "stress_return_at_least_9pct": stress["annualized_return"] >= 0.09,
        "stress_sharpe_at_least_065": stress["sharpe"] >= 0.65,
        "worst_day_within_8pct": float(diagnostics["worst_day"]) >= -0.08,
        "expected_shortfall_95_within_35pct": (
            float(diagnostics["expected_shortfall_95"]) >= -0.035
        ),
        "quality_correlation_at_most_050": (
            abs(float(diagnostics["quality_correlation"])) <= 0.50
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
        "at_least_1650_common_days": len(panel.calendar) >= 1650,
        "all_assets_start_before_2020": all(
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
        (EXPERIMENT_ID, "A股科技红利黄金等权"),
        (TECH_DIVIDEND_ID, "A股科技红利50/50"),
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
            "A股科技红利黄金等权通过冻结门槛，仅允许前向研究观察"
            if passed
            else f"A股科技红利黄金等权未通过门槛（{', '.join(failed)}），归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "国内三风格等权研究报告"),
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
