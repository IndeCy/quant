"""Quality 慢核心与意外盈利事件卫星组合研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.benchmark_series import load_adjusted_fund_curve
from data.earnings_surprise import (
    EarningsSurprisePaths,
    attach_earnings_surprise_database,
    create_earnings_surprise_signal_date_table,
    materialize_earnings_surprise_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.quality_financial import (
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.earnings_surprise_data_feasibility_study import (
    load_earnings_surprise_candidates,
)
from examples.earnings_surprise_strategy_study import build_event_targets
from examples.quality_balanced_value_buffered_study import (
    BASELINE_ID,
    STUDY_START,
    _annual_metrics,
    _data_version,
    _equal_weight_targets,
    _financial_paths,
    _run_candidate,
    _score_candidates,
)
from examples.quality_balanced_value_size_neutral_study import (
    PERIODS,
    _style_residual,
)
from examples.quality_factor_study_support import build_period_metrics
from factors.earnings_surprise import score_earnings_surprise_rank_frame
from portfolio.topn import build_topn_selections
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


EXPERIMENT_ID = "quality_earnings_event_satellite_80_20_v1"
EVENT_ID = "earnings_surprise_event_rank_same_snapshot_v2"
REPORT_PATH = Path("docs/research/quality-earnings-event-satellite-80-20-v1.md")
CORE_WEIGHT = 0.80
EVENT_WEIGHT = 0.20
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality慢核心 × 意外盈利事件卫星 80/20 V1",
    category="portfolio_strategy",
    hypothesis="慢速Quality核心叠加小比例季度意外盈利事件卫星，能否改善锁定期而不放大回撤和换手",
    definition={
        "core": {
            "strategy_id": "quality_balanced_value_v1",
            "weight": CORE_WEIGHT,
            "definition_unchanged": True,
        },
        "event_satellite": {
            "strategy_id": "earnings_surprise_event_rank_v2",
            "weight": EVENT_WEIGHT,
            "factor": "raw_sue_percentile_rank",
            "event_age_days": 90,
            "top_n": 20,
            "unconstructible_month": "carry_previous_event_target",
            "before_first_constructible": "core_100pct",
            "definition_unchanged": True,
        },
        "portfolio": {
            "rebalance": "monthly",
            "weight": "equal_inside_each_sleeve",
            "overlap": "sum_sleeve_weights",
            "allocation_grid": False,
        },
        "risk_overlay": {
            "scheme": "GRID",
            "window": 20,
            "volatility_threshold": 0.45,
            "reduced_exposure": 0.30,
            "frequency": "daily",
            "applied_to_whole_portfolio": True,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
        },
        "style_residual": {
            "style": "510500_minus_510300_annual",
            "validation_train": [2015, 2016, 2017, 2018],
            "validation_apply": [2019, 2020, 2021],
            "locked_train": list(range(2015, 2022)),
            "locked_apply": list(range(2022, 2027)),
        },
        "frozen_gate": {
            "full_return_drag_vs_core_max": 0.01,
            "full_sharpe_at_least_core": True,
            "full_drawdown_worsening_max": 0.02,
            "locked_return_at_least_core": True,
            "locked_sharpe_at_least_core": True,
            "locked_drawdown_worsening_max": 0.02,
            "walk_forward_style_residual_all_checks": True,
            "annual_turnover_vs_core_max": 1.25,
            "event_core_daily_correlation_max": 0.75,
            "stress_annual_return": 0.09,
            "stress_sharpe": 0.55,
        },
        "decision": "research_only_never_auto_register",
        "methodology_version": "fixed_80_20_slow_core_event_satellite_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记固定80/20定义，再读取Quality与SUE点时截面。"""
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
        result = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """用同一次行情快照构造核心、事件和组合目标。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        raw_quality = load_annual_quality_candidates(connection)
        quality_filtered = apply_quality_universe_filters(raw_quality)
        quality_adjusted = attach_report_adjustment_factors(
            connection,
            quality_filtered,
        )
        quality_candidates, corporate_action_audit = (
            build_quality_value_lowvol_candidates(quality_adjusted)
        )
        quality_scores = _score_candidates(quality_candidates)
        quality_selections, quality_holdings = build_topn_selections(
            quality_scores,
            "factor_score",
            20,
        )
        quality_targets = _equal_weight_targets(quality_selections)

        create_earnings_surprise_signal_date_table(connection, signal_dates)
        attach_earnings_surprise_database(
            connection,
            EarningsSurprisePaths(paths.income_statement_path),
        )
        materialize_earnings_surprise_asof(connection)
        event_candidates = load_earnings_surprise_candidates(connection)
        event_targets, event_holdings, event_diagnostics = build_event_targets(
            event_candidates,
            signal_dates,
            scorer=score_earnings_surprise_rank_frame,
        )
        combined_targets, allocation_diagnostics = build_combined_targets(
            signal_dates,
            quality_targets,
            event_targets,
        )
        symbols = sorted(
            {
                symbol
                for mapping in (
                    quality_targets,
                    event_targets,
                    combined_targets,
                )
                for target in mapping.values()
                for symbol in target
            }
        )
        bars = load_feature_bars(connection, symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    hs300 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    csi500 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510500.SH",
        end_date=latest_date,
    )
    targets = {
        BASELINE_ID: quality_targets,
        EVENT_ID: event_targets,
        EXPERIMENT_ID: combined_targets,
    }
    runs = {
        strategy_id: _run_candidate(
            strategy_id,
            target,
            bars,
            calendar,
            hs300,
            slippage_bps=5.0,
        )
        for strategy_id, target in targets.items()
    }
    stress_run = _run_candidate(
        f"{EXPERIMENT_ID}_20bps",
        combined_targets,
        bars,
        calendar,
        hs300,
        slippage_bps=20.0,
    )
    periods = {
        name: (start, latest_date if end == "latest" else min(end, latest_date))
        for name, (start, end) in PERIODS.items()
        if start <= latest_date
    }
    period_metrics = build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        hs300,
        periods,
    )
    annual_metrics = _annual_metrics(runs, hs300, latest_date)
    stress_metrics = build_period_metrics(
        {"20bps": stress_run.result},
        hs300,
        {"full": (STUDY_START, latest_date)},
    )["20bps"]["full"]
    style_residual = _style_residual(runs, hs300, csi500)
    correlations = _daily_correlations(runs)
    gate = evaluate_gate(
        combined=period_metrics[EXPERIMENT_ID],
        core=period_metrics[BASELINE_ID],
        stress=stress_metrics,
        combined_residual=style_residual[EXPERIMENT_ID],
        event_core_correlation=correlations["event_core"],
    )
    latest_target_date = max(combined_targets)
    latest_target = combined_targets[latest_target_date]
    latest_holdings = [
        {
            "signal_date": latest_target_date,
            "symbol": symbol,
            "target_weight": weight,
            "in_quality_core": symbol in quality_targets.get(latest_target_date, {}),
            "in_event_satellite": _latest_target_contains(
                event_targets,
                latest_target_date,
                symbol,
            ),
        }
        for symbol, weight in sorted(
            latest_target.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": latest_date,
        "gate": gate,
        "decision": (
            "HISTORICAL_GATE_PASSED_FORWARD_CONFIRMATION_ONLY"
            if gate["passed"]
            else "REJECTED_NO_PRODUCTION_CHANGE"
        ),
        "period_metrics": period_metrics,
        "annual_metrics": annual_metrics,
        "stress_20bps_metrics": stress_metrics,
        "style_residual": style_residual,
        "daily_correlations": correlations,
        "event_diagnostics": event_diagnostics,
        "allocation_diagnostics": allocation_diagnostics,
        "corporate_action_audit": {
            "checked_rows": corporate_action_audit.checked_rows,
            "excluded_rows": corporate_action_audit.excluded_rows,
            "missing_rows": corporate_action_audit.missing_rows,
        },
        "quality_holding_records": len(quality_holdings),
        "event_holding_records": len(event_holdings),
        "latest_holdings": latest_holdings,
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def build_combined_targets(
    signal_dates: list[str],
    quality_targets: dict[str, dict[str, float]],
    event_targets: dict[str, dict[str, float]],
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """按月更新慢核心；事件不可构造时沿用上一次事件目标。"""
    combined: dict[str, dict[str, float]] = {}
    current_event: dict[str, float] | None = None
    event_active_months = 0
    overlaps: list[float] = []
    for signal_date in signal_dates:
        quality = quality_targets.get(signal_date)
        if not quality:
            continue
        if signal_date in event_targets:
            current_event = event_targets[signal_date]
        if current_event is None:
            combined[signal_date] = dict(quality)
            continue
        event_active_months += 1
        target: dict[str, float] = {}
        for symbol, weight in quality.items():
            target[symbol] = target.get(symbol, 0.0) + weight * CORE_WEIGHT
        for symbol, weight in current_event.items():
            target[symbol] = target.get(symbol, 0.0) + weight * EVENT_WEIGHT
        combined[signal_date] = target
        overlaps.append(
            len(set(quality).intersection(current_event))
            / max(len(current_event), 1)
        )
    return combined, {
        "combined_months": float(len(combined)),
        "event_active_months": float(event_active_months),
        "event_active_share": event_active_months / max(len(combined), 1),
        "median_sleeve_symbol_overlap": (
            float(pd.Series(overlaps).median()) if overlaps else 0.0
        ),
    }


def _latest_target_contains(
    targets: dict[str, dict[str, float]],
    target_date: str,
    symbol: str,
) -> bool:
    dates = [date for date in targets if date <= target_date]
    return bool(dates and symbol in targets[max(dates)])


def _daily_correlations(runs: dict[str, Any]) -> dict[str, float]:
    returns = {
        strategy_id: run.result.daily_values.pct_change()
        for strategy_id, run in runs.items()
    }
    return {
        "event_core": float(
            returns[EVENT_ID].corr(returns[BASELINE_ID])
        ),
        "combined_core": float(
            returns[EXPERIMENT_ID].corr(returns[BASELINE_ID])
        ),
        "combined_event": float(
            returns[EXPERIMENT_ID].corr(returns[EVENT_ID])
        ),
    }


def evaluate_gate(
    *,
    combined: dict[str, dict[str, float]],
    core: dict[str, dict[str, float]],
    stress: dict[str, float],
    combined_residual: dict[str, Any],
    event_core_correlation: float,
) -> dict[str, Any]:
    """事件袖套必须改善锁定期且不破坏核心的长期风险收益。"""
    full = combined["full"]
    locked = combined["locked_test"]
    core_full = core["full"]
    core_locked = core["locked_test"]
    checks = {
        "full_return_drag_within_1pct": (
            full["annualized_return"] >= core_full["annualized_return"] - 0.01
        ),
        "full_sharpe_at_least_core": full["sharpe"] >= core_full["sharpe"],
        "full_drawdown_worsening_within_2pct": (
            full["max_drawdown"] >= core_full["max_drawdown"] - 0.02
        ),
        "locked_return_at_least_core": (
            locked["annualized_return"] >= core_locked["annualized_return"]
        ),
        "locked_sharpe_at_least_core": locked["sharpe"] >= core_locked["sharpe"],
        "locked_drawdown_worsening_within_2pct": (
            locked["max_drawdown"] >= core_locked["max_drawdown"] - 0.02
        ),
        "walk_forward_style_residual_gate_passed": bool(
            combined_residual["gate_passed"]
        ),
        "annual_turnover_not_over_core_125pct": (
            full["annual_turnover"] <= core_full["annual_turnover"] * 1.25
        ),
        "event_core_daily_correlation_at_most_075": (
            abs(event_core_correlation) <= 0.75
        ),
        "stress_20bps_annual_return_at_least_9pct": (
            stress["annualized_return"] >= 0.09
        ),
        "stress_20bps_sharpe_at_least_055": stress["sharpe"] >= 0.55,
    }
    return {"passed": all(checks.values()), "checks": checks}


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED" if passed else "REJECTED",
        decision_reason=(
            "固定80/20事件卫星通过全部门槛，仅进入冻结前瞻确认"
            if passed
            else "固定80/20事件卫星未通过全部门槛，不修改现有策略或生产调度"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "事件卫星研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新组合目标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows: list[str] = []
    for strategy_id in (BASELINE_ID, EVENT_ID, EXPERIMENT_ID):
        for period in (
            "2015_2017",
            "2018_2020",
            "2021_2023",
            "2024_latest",
            "locked_test",
            "full",
        ):
            item = result["period_metrics"][strategy_id][period]
            rows.append(
                f"| {strategy_id} | {period} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['excess_return']:.2%} | {item['annual_turnover']:.2f}x |"
            )
    residual = result["style_residual"][EXPERIMENT_ID]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    correlations = result["daily_correlations"]
    event = result["event_diagnostics"]
    allocation = result["allocation_diagnostics"]
    stress = result["stress_20bps_metrics"]
    return f"""# Quality慢核心 × 意外盈利事件卫星 80/20 V1

- 数据截止：{result['latest_date']}。
- Core 80%：冻结的 Quality Balanced Value。
- Satellite 20%：冻结的 SUE 原始秩 Top20；不可构造月份沿用。
- 组合月频更新，日频统一风险层，M0 T+1执行。
- 没有权重网格，不修改生产策略或调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 袖套与执行诊断

- SUE实际重选/沿用月份：
  {event['rebalance_months']:.0f} / {event['carried_months']:.0f}。
- 事件卫星有效月份占比：{allocation['event_active_share']:.2%}。
- 两袖套持仓代码重叠中位数：
  {allocation['median_sleeve_symbol_overlap']:.2%}。
- 事件与核心日收益相关：
  {correlations['event_core']:.3f}。
- 组合与核心/事件相关：
  {correlations['combined_core']:.3f} /
  {correlations['combined_event']:.3f}。
- 20bps压力年化/Sharpe：
  {stress['annualized_return']:.2%} / {stress['sharpe']:.3f}。

## 组合走步中盘风格残差

- 验证/锁定Beta：
  {residual['validation_beta']:.3f} / {residual['locked_beta']:.3f}。
- 验证/锁定平均残差：
  {residual['validation_mean_residual']:.2%} /
  {residual['locked_mean_residual']:.2%}。
- 锁定正残差年占比/IR/最差年：
  {residual['locked_positive_year_share']:.1%} /
  {residual['locked_residual_information_ratio']:.3f} /
  {residual['locked_worst_residual']:.2%}。
- 残差门槛：{'PASS' if residual['gate_passed'] else 'FAIL'}。

## 预注册门槛

{checks}

结论：{result['decision']}。
"""


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
