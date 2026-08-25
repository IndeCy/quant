"""A股科技行业ETF周频相对强度与趋势过滤策略。"""

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
from examples.a_share_tech_etf_rotation_report import render_report
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.etf_relative_strength import (
    calculate_relative_strength_states,
    weekly_signal_dates,
)
from portfolio.tech_etf_rotation import build_tech_rotation_targets
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


EXPERIMENT_ID = "a_share_tech_etf_weekly_relative_strength_v1"
REPORT_PATH = Path("docs/research/a-share-tech-etf-weekly-relative-strength-v1.md")
TECH_NAMES = {
    "512480.SH": "半导体ETF",
    "515880.SH": "通信ETF",
    "512720.SH": "计算机ETF",
    "512930.SH": "人工智能ETF",
    "515000.SH": "科技龙头ETF",
}
TECH_SYMBOLS = list(TECH_NAMES)
BOND = "511010.SH"
BENCHMARK = "510300.SH"
MOMENTUM_WINDOW = 20
TREND_WINDOW = 60
TOP_N = 2
SLOT_WEIGHT = 0.40
DEFENSIVE_BASE_WEIGHT = 0.20
LOAD_START = "20190823"
STUDY_START = "20200101"
LOCKED_START = "20240101"
RELIABLE_AS_OF = "20260728"
EQUAL_ID = "tech_etf_equal_weekly_control"
SEMICONDUCTOR_ID = "semiconductor_direct_control"
BENCHMARK_ID = "hs300_direct_tech_control"
STRESS_ID = "a_share_tech_etf_rotation_cost_30bps"
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
    name="A股科技ETF周频相对强度轮动 V1",
    category="allocation_strategy",
    hypothesis=(
        "固定科技行业ETF池的周频相对强度与独立趋势过滤，"
        "能否比静态科技等权更快适应A股主线并用国债空槽降低尾部"
    ),
    definition={
        "universe": {
            "symbols": TECH_NAMES,
            "survivorship_policy": "all_symbols_listed_before_study_start",
            "fixed_before_reading_returns": True,
        },
        "signal": {
            "momentum": "close_t/close_t_minus_20-1",
            "trend": "close_gt_ma60_and_positive_momentum",
            "ranking": "cross_section_descending",
            "signal_time": "last_trading_day_of_week_close",
        },
        "portfolio": {
            "top_n": TOP_N,
            "slot_weight": SLOT_WEIGHT,
            "defensive_base_weight": DEFENSIVE_BASE_WEIGHT,
            "unused_slots_to": BOND,
            "rebalance": "weekly",
            "parameter_grid": False,
        },
        "controls": {
            "equal_weight_same_pool": {
                symbol: 1.0 / len(TECH_SYMBOLS)
                for symbol in TECH_SYMBOLS
            },
            "semiconductor_direct": {"512480.SH": 1.0},
            "hs300_direct": {BENCHMARK: 1.0},
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 10.0,
            "stress_slippage_bps": 30.0,
            "stamp_tax_rate": 0.0,
        },
        "evaluation": {
            "periods": PERIODS,
            "full_return_min": 0.08,
            "full_drawdown_floor": -0.30,
            "full_sharpe_min": 0.55,
            "full_calmar_min": 0.25,
            "positive_excess_vs_hs300": True,
            "return_lift_vs_equal_min": 0.0,
            "drawdown_improvement_vs_equal_min": 0.05,
            "sharpe_lift_vs_equal_min": 0.10,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.35,
            "median_fold_sharpe_min": 0.40,
            "locked_return_min": 0.06,
            "locked_drawdown_floor": -0.28,
            "locked_sharpe_min": 0.45,
            "annual_turnover_max": 12.0,
            "positive_years_min": 4,
            "stress_return_min": 0.07,
            "stress_sharpe_min": 0.50,
            "worst_day_floor": -0.09,
            "expected_shortfall_95_floor": -0.035,
            "quality_correlation_max": 0.75,
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "weekly_tech_rotation_multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """申请研究指纹后再读取完整基金面板。"""
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
        result, runs, targets, states, holdings = _calculate(
            paths,
            normalized_as_of,
        )
        _complete_attempt(
            attempt,
            result,
            runs,
            targets,
            states,
            holdings,
        )
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
    pd.DataFrame,
    pd.DataFrame,
]:
    symbols = [*TECH_SYMBOLS, BOND, BENCHMARK]
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        symbols,
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    audit = audit_panel(panel, symbols, as_of_date)
    if not audit["passed"]:
        raise ValueError(f"tech ETF panel audit failed: {audit}")
    signals = [
        date
        for date in weekly_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    states = calculate_relative_strength_states(
        panel.adjusted_close,
        signals,
        TECH_SYMBOLS,
        momentum_window=MOMENTUM_WINDOW,
        trend_window=TREND_WINDOW,
    )
    candidate_targets, holdings = build_tech_rotation_targets(
        states,
        defensive_symbol=BOND,
        top_n=TOP_N,
        slot_weight=SLOT_WEIGHT,
        defensive_base_weight=DEFENSIVE_BASE_WEIGHT,
    )
    equal_weights = {
        symbol: 1.0 / len(TECH_SYMBOLS)
        for symbol in TECH_SYMBOLS
    }
    target_sets = {
        EXPERIMENT_ID: candidate_targets,
        EQUAL_ID: _fixed_targets(signals, equal_weights),
        SEMICONDUCTOR_ID: _fixed_targets(signals, {"512480.SH": 1.0}),
        BENCHMARK_ID: _fixed_targets(signals, {BENCHMARK: 1.0}),
        STRESS_ID: candidate_targets,
    }
    benchmark = _benchmark_curve(panel)
    runs = {
        strategy_id: _run(
            strategy_id,
            targets,
            panel,
            benchmark,
            slippage_bps=30.0 if strategy_id == STRESS_ID else 10.0,
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
    diagnostics = build_diagnostics(
        paths,
        runs[EXPERIMENT_ID],
        candidate_targets,
    )
    gate = evaluate_gate(metrics, annual, diagnostics, audit)
    latest_holdings = build_latest_holdings(holdings)
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
        "latest_holdings": latest_holdings,
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, target_sets, states, holdings


def build_diagnostics(
    paths: RuntimePaths,
    run: RiskLayerRun,
    targets: dict[str, dict[str, float]],
) -> dict[str, float | int]:
    nav = run.result.daily_values.loc[STUDY_START:].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    drawdown = nav / nav.cummax() - 1.0
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift(fill_value=False)).cumsum()
    lengths = underwater.groupby(groups).sum()
    risky_weights = [
        1.0 - weights.get(BOND, 0.0)
        for weights in targets.values()
    ]
    return {
        "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)),
        "worst_day": float(returns.min()),
        "expected_shortfall_95": float(
            returns[returns.le(threshold)].mean()
        ),
        "max_underwater_days": int(lengths.max()) if len(lengths) else 0,
        "average_risky_target_weight": float(pd.Series(risky_weights).mean()),
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
    equal = metrics[EQUAL_ID]["full"]
    benchmark = metrics[BENCHMARK_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    checks = {
        "data_audit": bool(audit["passed"]),
        "full_return_at_least_8pct": full["annualized_return"] >= 0.08,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_055": full["sharpe"] >= 0.55,
        "full_calmar_at_least_025": full["calmar"] >= 0.25,
        "positive_excess_vs_hs300": (
            full["annualized_return"] > benchmark["annualized_return"]
        ),
        "return_lift_vs_equal_nonnegative": (
            full["annualized_return"] >= equal["annualized_return"]
        ),
        "drawdown_improvement_vs_equal_at_least_5pct": (
            full["max_drawdown"] - equal["max_drawdown"] >= 0.05
        ),
        "sharpe_lift_vs_equal_at_least_010": (
            full["sharpe"] - equal["sharpe"] >= 0.10
        ),
        "all_three_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_35pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.35,
        "median_fold_sharpe_at_least_040": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.40,
        "locked_return_at_least_6pct": locked["annualized_return"] >= 0.06,
        "locked_drawdown_within_28pct": locked["max_drawdown"] >= -0.28,
        "locked_sharpe_at_least_045": locked["sharpe"] >= 0.45,
        "annual_turnover_below_12x": full["annual_turnover"] <= 12.0,
        "at_least_four_positive_years": positive_years >= 4,
        "stress_return_at_least_7pct": stress["annualized_return"] >= 0.07,
        "stress_sharpe_at_least_050": stress["sharpe"] >= 0.50,
        "worst_day_within_9pct": float(diagnostics["worst_day"]) >= -0.09,
        "expected_shortfall_95_within_35pct": (
            float(diagnostics["expected_shortfall_95"]) >= -0.035
        ),
        "quality_correlation_at_most_075": (
            abs(float(diagnostics["quality_correlation"])) <= 0.75
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
    }


def build_latest_holdings(holdings: pd.DataFrame) -> list[dict[str, Any]]:
    latest = str(holdings["signal_date"].max())
    rows = holdings.loc[holdings["signal_date"].eq(latest)].copy()
    return [
        {
            "symbol": str(row.symbol),
            "name": TECH_NAMES.get(str(row.symbol), "5年国债ETF"),
            "target_weight": float(row.target_weight),
            "role": str(row.role),
        }
        for row in rows.sort_values(
            ["role", "target_weight", "symbol"],
            ascending=[True, False, True],
        ).itertuples(index=False)
    ]


def audit_panel(
    panel: FundPortfolioPanel,
    symbols: list[str],
    as_of_date: str,
) -> dict[str, Any]:
    expected = set(symbols)
    covered = {str(item["symbol"]) for item in panel.coverage}
    lag = (pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)).days
    checks = {
        "all_assets_present": covered == expected,
        "latest_within_five_days": 0 <= lag <= 5,
        "at_least_1600_common_days": len(panel.calendar) >= 1600,
        "all_study_assets_start_before_2020": all(
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
    states: pd.DataFrame,
    holdings: pd.DataFrame,
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
    targets_path = attempt.output_dir / "weekly_targets.csv"
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
    states_path = attempt.output_dir / "weekly_states.csv"
    states.to_csv(states_path, index=False)
    holdings_path = attempt.output_dir / "weekly_holdings.csv"
    holdings.to_csv(holdings_path, index=False)
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
        (EXPERIMENT_ID, "科技ETF周频轮动"),
        (EQUAL_ID, "科技ETF静态等权"),
        (BENCHMARK_ID, "沪深300ETF"),
    ]:
        nav = runs[series_id].result.daily_values.astype(float)
        normalized = nav / float(nav.iloc[0])
        series_rows.extend(
            {
                "series_id": series_id,
                "series_name": series_name,
                "trade_date": date.strftime("%Y%m%d"),
                "nav": float(value),
                "adjust_policy": "qfq_m0_t1_10bps",
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
            "科技ETF周频轮动通过冻结门槛，仅允许研究级前向观察"
            if passed
            else f"科技ETF周频轮动未通过门槛（{', '.join(failed)}），归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "科技ETF轮动研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("weekly_targets", targets_path, "周频目标"),
            ExperimentArtifact("weekly_states", states_path, "周频强度状态"),
            ExperimentArtifact("weekly_holdings", holdings_path, "周频持仓"),
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
