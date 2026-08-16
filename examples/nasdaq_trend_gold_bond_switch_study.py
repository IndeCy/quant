"""纳指长期趋势在纳指黄金进攻块与黄金国债防守块之间切换。"""

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
from examples.nasdaq_trend_gold_bond_switch_report import render_report
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.etf_independent_trend import calculate_independent_trend_states
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


EXPERIMENT_ID = "nasdaq_trend_gold_bond_switch_v1"
REPORT_PATH = Path("docs/research/nasdaq-trend-gold-bond-switch-v1.md")
NASDAQ = "159941.SZ"
GOLD = "518880.SH"
BOND = "511010.SH"
SP500 = "513500.SH"
BENCHMARK = "510300.SH"
FAST_WINDOW = 20
SLOW_WINDOW = 200
RELIABLE_AS_OF = "20260728"
LOAD_START = "20150713"
OOS_START = "20190101"
LOCKED_START = "20220101"
ACTIVE_WEIGHTS = {NASDAQ: 0.60, GOLD: 0.40}
DEFENSIVE_WEIGHTS = {GOLD: 0.50, BOND: 0.50}
STATIC_ID = "nasdaq_gold_static_60_40_control"
SP500_ID = "sp500_direct_switch_control"
NASDAQ_ID = "nasdaq_direct_switch_control"
STRESS_ID = "nasdaq_trend_gold_bond_switch_cost_20bps"
FOLD_KEYS = ("2019_2021", "2022_2024", "2025_latest")
PERIODS = {
    "2019_2021": ("20190101", "20211231"),
    "2022_2024": ("20220101", "20241231"),
    "2025_latest": ("20250101", "LATEST"),
    "locked_test": (LOCKED_START, "LATEST"),
    "oos_full": (OOS_START, "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="纳指趋势驱动黄金国债切换 V1",
    category="allocation_strategy",
    hypothesis=(
        "纳指长期趋势转弱时从纳指黄金60/40切换到黄金国债50/50，"
        "能否保留相对场内标普500的收益优势并显著降低尾部回撤"
    ),
    definition={
        "assets": {
            "risk": NASDAQ,
            "diversifier": GOLD,
            "defensive": BOND,
            "hard_opportunity_cost": SP500,
        },
        "signal": {
            "formula": "nasdaq_ma20_gt_ma200",
            "signal_time": "month_end_close",
            "future_data": "forbidden",
        },
        "portfolio": {
            "trend_active": ACTIVE_WEIGHTS,
            "trend_inactive": DEFENSIVE_WEIGHTS,
            "rebalance": "monthly",
            "weight_grid": False,
            "leverage": 1.0,
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
            "oos_return_min": 0.12,
            "oos_drawdown_floor": -0.20,
            "oos_sharpe_min": 1.00,
            "oos_calmar_min": 0.60,
            "return_lift_vs_sp500_min": 0.005,
            "sharpe_lift_vs_sp500_min": 0.10,
            "return_shortfall_vs_static_max": 0.04,
            "drawdown_improvement_vs_static_min": 0.02,
            "all_folds_positive": True,
            "worst_fold_drawdown_floor": -0.22,
            "median_fold_sharpe_min": 0.75,
            "locked_return_min": 0.10,
            "locked_drawdown_floor": -0.20,
            "locked_sharpe_min": 0.85,
            "positive_years_min": 6,
            "annual_turnover_max": 2.0,
            "stress_return_min": 0.11,
            "stress_sharpe_min": 0.90,
            "worst_day_floor": -0.08,
            "expected_shortfall_95_floor": -0.025,
            "quality_correlation_max": 0.50,
            "active_day_share_range": [0.35, 0.85],
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "nasdaq_regime_switch_multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记完整研究语义后再读取基金大表。"""
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
        result, runs, targets, states = _calculate(paths, normalized_as_of)
        _complete_attempt(attempt, result, runs, targets, states)
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
]:
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [NASDAQ, GOLD, BOND, SP500, BENCHMARK],
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    audit = audit_panel(panel, as_of_date)
    if not audit["passed"]:
        raise ValueError(f"fund panel audit failed: {audit}")
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(OOS_START)
    ]
    states = calculate_independent_trend_states(
        panel.adjusted_close,
        signals,
        [NASDAQ],
        fast_window=FAST_WINDOW,
        slow_window=SLOW_WINDOW,
    )
    candidate_targets = build_switch_targets(states)
    target_sets = {
        EXPERIMENT_ID: candidate_targets,
        STATIC_ID: _fixed_targets(signals, ACTIVE_WEIGHTS),
        SP500_ID: _fixed_targets(signals, {SP500: 1.0}),
        NASDAQ_ID: _fixed_targets(signals, {NASDAQ: 1.0}),
        STRESS_ID: candidate_targets,
    }
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
        if year >= OOS_START[:4]
    }
    attribution = build_state_attribution(
        runs[EXPERIMENT_ID],
        states,
        panel.calendar,
    )
    diagnostics = build_diagnostics(paths, runs)
    gate = evaluate_gate(metrics, annual, diagnostics, attribution, audit)
    latest = states.sort_values("signal_date").iloc[-1]
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "data_audit": audit,
        "period_metrics": metrics[EXPERIMENT_ID],
        "full_comparison": {
            name: values["oos_full"]
            for name, values in metrics.items()
            if name != STRESS_ID
        },
        "annual_metrics": annual,
        "state_attribution": attribution,
        "diagnostics": diagnostics,
        "latest_state": {
            "signal_date": str(latest["signal_date"]),
            "trend_active": bool(latest["trend_active"]),
            "fast_ma": float(latest["ma60"]),
            "slow_ma": float(latest["ma120"]),
        },
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, target_sets, states


def build_switch_targets(
    states: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """把冻结的纳指趋势状态映射成进攻或防守目标。"""
    targets: dict[str, dict[str, float]] = {}
    for row in states.itertuples(index=False):
        weights = ACTIVE_WEIGHTS if bool(row.trend_active) else DEFENSIVE_WEIGHTS
        targets[str(row.signal_date)] = dict(weights)
    return targets


def build_state_attribution(
    run: RiskLayerRun,
    states: pd.DataFrame,
    calendar: list[pd.Timestamp],
) -> dict[str, dict[str, float]]:
    """按T+1生效状态拆解日收益，验证状态不是同日偷看。"""
    index = pd.DatetimeIndex(calendar)
    effective: dict[pd.Timestamp, str] = {}
    for row in states.itertuples(index=False):
        signal = pd.Timestamp(str(row.signal_date))
        location = int(index.searchsorted(signal, side="right"))
        if location < len(index):
            effective[index[location]] = (
                "NASDAQ_GOLD_ACTIVE"
                if bool(row.trend_active)
                else "GOLD_BOND_DEFENSIVE"
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
        }
    return result


def build_diagnostics(
    paths: RuntimePaths,
    runs: dict[str, RiskLayerRun],
) -> dict[str, float | int]:
    """计算OOS尾部、波动与Quality独立性。"""
    nav = runs[EXPERIMENT_ID].result.daily_values.loc[OOS_START:].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    drawdown = nav / nav.cummax() - 1.0
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift(fill_value=False)).cumsum()
    lengths = underwater.groupby(groups).sum()
    return {
        "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)),
        "worst_day": float(returns.min()),
        "expected_shortfall_95": float(
            returns[returns.le(threshold)].mean()
        ),
        "max_underwater_days": int(lengths.max()) if len(lengths) else 0,
        "quality_correlation": global_study.load_quality_correlation(
            paths,
            runs[EXPERIMENT_ID],
        ),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, float]],
    diagnostics: dict[str, float | int],
    attribution: dict[str, dict[str, float]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """执行绝对收益、机会成本、尾部和稳定性硬门槛。"""
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["oos_full"]
    locked = candidate["locked_test"]
    static = metrics[STATIC_ID]["oos_full"]
    sp500 = metrics[SP500_ID]["oos_full"]
    stress = metrics[STRESS_ID]["oos_full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    active_share = attribution.get("NASDAQ_GOLD_ACTIVE", {}).get(
        "day_share",
        0.0,
    )
    checks = {
        "data_audit": bool(audit["passed"]),
        "oos_return_at_least_12pct": full["annualized_return"] >= 0.12,
        "oos_drawdown_within_20pct": full["max_drawdown"] >= -0.20,
        "oos_sharpe_at_least_100": full["sharpe"] >= 1.00,
        "oos_calmar_at_least_060": full["calmar"] >= 0.60,
        "return_lift_vs_sp500_at_least_05pct": (
            full["annualized_return"] - sp500["annualized_return"] >= 0.005
        ),
        "sharpe_lift_vs_sp500_at_least_010": (
            full["sharpe"] - sp500["sharpe"] >= 0.10
        ),
        "return_shortfall_vs_static_within_4pct": (
            static["annualized_return"] - full["annualized_return"] <= 0.04
        ),
        "drawdown_improvement_vs_static_at_least_2pct": (
            full["max_drawdown"] - static["max_drawdown"] >= 0.02
        ),
        "all_three_folds_positive": all(
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
        "locked_return_at_least_10pct": locked["annualized_return"] >= 0.10,
        "locked_drawdown_within_20pct": locked["max_drawdown"] >= -0.20,
        "locked_sharpe_at_least_085": locked["sharpe"] >= 0.85,
        "at_least_six_positive_years": positive_years >= 6,
        "annual_turnover_below_2x": full["annual_turnover"] <= 2.0,
        "stress_return_at_least_11pct": stress["annualized_return"] >= 0.11,
        "stress_sharpe_at_least_090": stress["sharpe"] >= 0.90,
        "worst_day_within_8pct": float(diagnostics["worst_day"]) >= -0.08,
        "expected_shortfall_95_within_25pct": (
            float(diagnostics["expected_shortfall_95"]) >= -0.025
        ),
        "quality_correlation_at_most_050": (
            abs(float(diagnostics["quality_correlation"])) <= 0.50
        ),
        "active_day_share_between_35_and_85pct": (
            0.35 <= active_share <= 0.85
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
        "active_day_share": active_share,
    }


def audit_panel(
    panel: FundPortfolioPanel,
    as_of_date: str,
) -> dict[str, Any]:
    expected = {NASDAQ, GOLD, BOND, SP500, BENCHMARK}
    covered = {str(item["symbol"]) for item in panel.coverage}
    lag = (pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)).days
    checks = {
        "all_assets_present": covered == expected,
        "latest_within_five_days": 0 <= lag <= 5,
        "at_least_2600_common_days": len(panel.calendar) >= 2600,
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
) -> None:
    """保存报告、完整对照净值、目标、状态和诊断。"""
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
    states_path = attempt.output_dir / "monthly_states.csv"
    states.to_csv(states_path, index=False)
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
        (EXPERIMENT_ID, "纳指趋势黄金国债切换"),
        (STATIC_ID, "静态纳指黄金60/40"),
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
            if date >= pd.Timestamp(OOS_START)
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
            "纳指趋势切换通过冻结门槛，仅允许独立前向观察"
            if passed
            else f"纳指趋势切换未通过门槛（{', '.join(failed)}），归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "纳指趋势切换研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与机会成本净值"),
            ExperimentArtifact("monthly_targets", targets_path, "完整月度目标"),
            ExperimentArtifact("monthly_states", states_path, "纳指趋势状态"),
            ExperimentArtifact("diagnostics", diagnostics_path, "尾部与门槛诊断"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定基金历史、增量与Quality监控数据版本。"""
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
