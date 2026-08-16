"""主线链动仅在修复趋势状态启用的固定条件式卫星研究。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.mainline_conditional_satellite_report import render_report
from examples.mainline_trend_regime_attribution_metrics import (
    classify_lagged_trend_regime,
)
from examples.mainline_trend_regime_attribution_study import (
    _load_market_states,
)
from examples.quality_mainline_diversification_metrics import metric_summary
from examples.quality_mainline_diversification_study import (
    CORE_ID,
    SATELLITE_ID,
    audit_common_history,
    load_strategy_histories,
    simulate_monthly_allocation,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "mainline_risk_positive_conditional_70_30_v1"
REPORT_PATH = Path(
    "docs/research/mainline-risk-positive-conditional-70-30-v1.md"
)
ACTIVE_REGIME = "RISK_POSITIVE"
CORE_ACTIVE_WEIGHT = 0.70
SATELLITE_ACTIVE_WEIGHT = 0.30
ALLOCATION_COST_BPS = 10.0
FOLDS = {
    "2020_2021": ("20200615", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="主线链动 RISK_POSITIVE 条件式卫星 V1",
    category="conditional_portfolio_research",
    hypothesis="仅在长期趋势未确认但20日收益转正时启用主线链动，能否减少固定卫星的阶段性拖累",
    definition={
        "sleeves": {
            "core": CORE_ID,
            "satellite": SATELLITE_ID,
        },
        "active_regime": {
            "label": ACTIVE_REGIME,
            "definition": "MA60_lt_MA120_and_benchmark_return_20d_gt_0",
            "visibility": "close_T_effective_T_plus_1",
        },
        "allocation": {
            "active": {"core": 0.70, "satellite": 0.30},
            "inactive": {"core": 1.0, "satellite": 0.0},
            "between_transitions": "weights_drift_with_returns",
            "cost_bps": ALLOCATION_COST_BPS,
        },
        "comparison": ["core_100", "fixed_70_30"],
        "folds": FOLDS,
        "frozen_gate": {
            "annual_return_at_least_core": True,
            "sharpe_at_least_core": True,
            "drawdown_worse_than_core_max": 0.01,
            "drawdown_floor": -0.20,
            "positive_excess": True,
            "all_folds_positive": True,
            "repair_2022_2023_to_positive": True,
            "sharpe_at_least_fixed_70_30": True,
            "allocation_turnover_max": 3.0,
            "annualized_cost_drag_max": 0.01,
            "active_day_share": [0.10, 0.30],
        },
        "selection_bias": (
            "active regime discovered on same history; "
            "passing requires forward-only observation"
        ),
        "no_strategy_or_factor_change": True,
        "never_directly_register_production": True,
        "parameters_fixed_before_backtest": True,
        "methodology_version": "conditional_sleeve_allocation_v1_1",
    },
)


@dataclass(frozen=True)
class ConditionalAllocationRun:
    """条件式组合运行结果。"""

    daily: pd.DataFrame
    annual_turnover: float
    total_cost: float
    transition_count: int


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """研究门禁通过后才读取完整历史。"""
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
        result, daily = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, daily)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """构造动态、固定和纯核心三条可比较净值。"""
    histories = load_strategy_histories(paths, as_of_date)
    audit = audit_common_history(histories)
    if not audit["passed"]:
        raise ValueError(f"strategy history audit failed: {audit}")
    common = histories[CORE_ID].merge(
        histories[SATELLITE_ID][["trade_date", "nav"]],
        on="trade_date",
        how="inner",
        suffixes=("_core", "_satellite"),
        validate="one_to_one",
    )
    market, _ = _load_market_states(paths, as_of_date)
    regimes = classify_lagged_trend_regime(market)
    conditional = simulate_conditional_allocation(
        common,
        regimes,
        cost_bps=ALLOCATION_COST_BPS,
    )
    fixed = simulate_monthly_allocation(
        common,
        core_weight=CORE_ACTIVE_WEIGHT,
        satellite_weight=SATELLITE_ACTIVE_WEIGHT,
        cost_bps=ALLOCATION_COST_BPS,
    )
    daily = conditional.daily.merge(
        fixed.daily[
            ["trade_date", "portfolio_nav", "allocation_turnover"]
        ].rename(
            columns={
                "portfolio_nav": "fixed_nav",
                "allocation_turnover": "fixed_allocation_turnover",
            }
        ),
        on="trade_date",
        how="inner",
        validate="one_to_one",
    )
    periods = {
        name: (start, audit["end_date"] if end == "LATEST" else end)
        for name, (start, end) in FOLDS.items()
    }
    periods["full"] = (audit["start_date"], audit["end_date"])
    period_metrics = build_period_metrics(daily, periods)
    active_share = float(
        (daily["satellite_weight_open"] > 0).mean()
    )
    gate = evaluate_gate(
        period_metrics,
        active_share,
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            period_metrics,
            gate,
            audit,
            active_share,
            conditional.transition_count,
        ),
        encoding="utf-8",
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "as_of_date": as_of_date,
        "history_audit": audit,
        "period_metrics": period_metrics,
        "active_day_share": active_share,
        "transition_count": conditional.transition_count,
        "allocation_total_cost": conditional.total_cost,
        "gate": gate,
        "decision": (
            "FORWARD_OBSERVATION_REQUIRED"
            if gate["passed"]
            else "REJECTED"
        ),
        "production_registration_allowed": False,
        "report_path": str(report_path),
        "reused": False,
    }
    return result, daily


def simulate_conditional_allocation(
    common: pd.DataFrame,
    regimes: pd.DataFrame,
    *,
    cost_bps: float,
) -> ConditionalAllocationRun:
    """按前一收盘状态在当日开盘前切换目标袖套权重。"""
    if common.empty or regimes.empty or cost_bps < 0:
        raise ValueError("invalid conditional allocation inputs")
    frame = common.sort_values("trade_date").merge(
        regimes[["trade_date", "state_asof_date", "regime"]],
        on="trade_date",
        how="inner",
        validate="one_to_one",
    )
    frame["core_return"] = (
        pd.to_numeric(frame["nav_core"], errors="coerce")
        .pct_change()
        .fillna(0.0)
    )
    frame["satellite_return"] = (
        pd.to_numeric(frame["nav_satellite"], errors="coerce")
        .pct_change()
        .fillna(0.0)
    )
    benchmark = pd.to_numeric(frame["benchmark_nav"], errors="coerce")
    frame["benchmark_nav"] = benchmark / float(benchmark.iloc[0])
    initial_target = _target_weights(str(frame.iloc[0]["regime"]))
    weights = dict(initial_target)
    previous_target = dict(initial_target)
    portfolio_nav = 1.0
    gross_nav = 1.0
    total_cost = 0.0
    transitions = 0
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        target = _target_weights(str(row["regime"]))
        turnover = 0.0
        cost = 0.0
        if target != previous_target:
            turnover = 0.5 * sum(
                abs(target[name] - weights[name])
                for name in ["core", "satellite"]
            )
            cost = portfolio_nav * turnover * cost_bps / 10000.0
            portfolio_nav -= cost
            total_cost += cost
            transitions += 1
            weights = dict(target)
        core_return = float(row["core_return"])
        satellite_return = float(row["satellite_return"])
        portfolio_return = (
            weights["core"] * core_return
            + weights["satellite"] * satellite_return
        )
        portfolio_nav *= 1.0 + portfolio_return
        gross_nav *= 1.0 + portfolio_return
        denominator = 1.0 + portfolio_return
        core_close = weights["core"] * (1.0 + core_return) / denominator
        satellite_close = (
            weights["satellite"]
            * (1.0 + satellite_return)
            / denominator
        )
        records.append(
            {
                "trade_date": str(row["trade_date"]),
                "state_asof_date": str(row["state_asof_date"]),
                "regime": str(row["regime"]),
                "portfolio_nav": portfolio_nav,
                "gross_nav": gross_nav,
                "core_nav": float(row["nav_core"])
                / float(frame["nav_core"].iloc[0]),
                "satellite_nav": float(row["nav_satellite"])
                / float(frame["nav_satellite"].iloc[0]),
                "benchmark_nav": float(row["benchmark_nav"]),
                "core_return": core_return,
                "satellite_return": satellite_return,
                "core_weight_open": weights["core"],
                "satellite_weight_open": weights["satellite"],
                "allocation_turnover": turnover,
                "allocation_cost": cost,
            }
        )
        weights = {"core": core_close, "satellite": satellite_close}
        previous_target = target
    daily = pd.DataFrame(records)
    years = max((len(daily) - 1) / 252.0, 1.0 / 252.0)
    return ConditionalAllocationRun(
        daily=daily,
        annual_turnover=float(
            daily["allocation_turnover"].sum() / years
        ),
        total_cost=total_cost,
        transition_count=transitions,
    )


def build_period_metrics(
    daily: pd.DataFrame,
    periods: dict[str, tuple[str, str]],
) -> dict[str, dict[str, dict[str, float]]]:
    """统一比较条件式、固定式和纯核心组合。"""
    result: dict[str, dict[str, dict[str, float]]] = {}
    for period, (start, end) in periods.items():
        frame = daily[daily["trade_date"].between(start, end)].copy()
        years = max((len(frame) - 1) / 252.0, 1.0 / 252.0)
        turnover = float(frame["allocation_turnover"].sum() / years)
        fixed_turnover = float(
            frame["fixed_allocation_turnover"].sum() / years
        )
        conditional = metric_summary(
            frame["portfolio_nav"],
            frame["benchmark_nav"],
            turnover,
        )
        gross = metric_summary(
            frame["gross_nav"],
            frame["benchmark_nav"],
            turnover,
        )
        conditional["annualized_cost_drag"] = (
            gross["annualized_return"]
            - conditional["annualized_return"]
        )
        result[period] = {
            "conditional": conditional,
            "fixed_70_30": metric_summary(
                frame["fixed_nav"],
                frame["benchmark_nav"],
                fixed_turnover,
            ),
            "core": metric_summary(
                frame["core_nav"],
                frame["benchmark_nav"],
                0.0,
            ),
        }
    return result


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    active_share: float,
) -> dict[str, Any]:
    """执行历史门槛，但不消除同样本状态选择偏差。"""
    full = metrics["full"]
    conditional = full["conditional"]
    core = full["core"]
    fixed = full["fixed_70_30"]
    drawdown_gap = (
        abs(conditional["max_drawdown"]) - abs(core["max_drawdown"])
    )
    checks = {
        "annual_return_at_least_core": (
            conditional["annualized_return"]
            >= core["annualized_return"]
        ),
        "sharpe_at_least_core": conditional["sharpe"] >= core["sharpe"],
        "drawdown_worse_than_core_within_1pct": drawdown_gap <= 0.01,
        "drawdown_within_20pct": conditional["max_drawdown"] >= -0.20,
        "positive_excess": conditional["excess_return"] > 0,
        "all_folds_positive": all(
            metrics[name]["conditional"]["annualized_return"] > 0
            for name in FOLDS
        ),
        "repair_2022_2023_to_positive": (
            metrics["2022_2023"]["conditional"]["annualized_return"] > 0
        ),
        "sharpe_at_least_fixed_70_30": (
            conditional["sharpe"] >= fixed["sharpe"]
        ),
        "allocation_turnover_below_3x": (
            conditional["annual_turnover"] <= 3.0
        ),
        "annualized_cost_drag_below_1pct": (
            conditional["annualized_cost_drag"] <= 0.01
        ),
        "active_day_share_between_10_and_30pct": (
            0.10 <= active_share <= 0.30
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "drawdown_gap_vs_core": drawdown_gap,
        "selection_bias_requires_forward_test": True,
    }


def _target_weights(regime: str) -> dict[str, float]:
    if regime == ACTIVE_REGIME:
        return {
            "core": CORE_ACTIVE_WEIGHT,
            "satellite": SATELLITE_ACTIVE_WEIGHT,
        }
    return {"core": 1.0, "satellite": 0.0}


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    daily: pd.DataFrame,
) -> None:
    """归档净值和历史门槛，不创建策略配置。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    daily_path = attempt.output_dir / "daily_nav.csv"
    daily.to_csv(daily_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "FORWARD_OBSERVATION_REQUIRED" if passed else "REJECTED"
        ),
        decision_reason=(
            "历史门槛通过，但存在同样本状态选择偏差，仅允许前向观察"
            if passed
            else "条件式卫星未通过冻结历史门槛，停止该方向"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "条件式卫星报告"),
            ExperimentArtifact("daily_nav", daily_path, "条件式组合每日净值"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定监控事实库和底层策略声明。"""
    files = [
        paths.monitoring_path,
        paths.config_dir / "strategies" / f"{CORE_ID}.json",
        paths.config_dir / "strategies" / f"{SATELLITE_ID}.json",
    ]
    return "|".join(
        f"{path.name}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for path in files
    )


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
