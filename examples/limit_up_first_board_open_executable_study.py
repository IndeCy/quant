"""用开盘时点涨跌停状态复核首板封单强度事件策略。"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples import limit_up_first_board_strategy_study as base
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
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


EXPERIMENT_ID = "limit_up_first_board_open_executable_v1"
CONTROL_ID = "limit_up_first_board_amount_open_executable_control"
STRESS_ID = "limit_up_first_board_open_executable_30bps"
AUDIT_ID = "limit_up_first_board_execution_assumption_audit_v1"
REPORT_PATH = Path(
    "docs/research/limit-up-first-board-open-executable-v1.md"
)

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="首板封单强度开盘可执行复核 V1",
    category="event_strategy_execution_correction",
    hypothesis=(
        "在只拦截开盘已经封住涨跌停的委托后，首板封单强度前10的次日开盘轮换"
        "是否仍能在成本、不可成交和分段门槛下形成可执行收益"
    ),
    definition={
        **base.RESEARCH_SPEC.definition,
        "dependency": AUDIT_ID,
        "execution": {
            **base.RESEARCH_SPEC.definition["execution"],
            "limit_state": "point_in_time_at_open",
            "buy_block": "open_at_upper_limit",
            "sell_block": "open_at_lower_limit",
        },
        "post_hoc_reason": (
            "原公共M0使用全天最高/最低价判断开盘委托，独立审计确认21.1%的目标买入"
            "属于开盘可买、盘中才触板"
        ),
        "parameters_fixed_before_corrected_return_loading": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "daily_first_board_open_point_in_time_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    normalized_as_of = min(
        str(as_of_date).replace("-", ""),
        base.RELIABLE_AS_OF,
    )
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized_as_of,
        data_version=base._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        _require_audit_passed(paths)
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
    events = base._load_events(paths.limit_list_increment_path, as_of_date)
    candidate_targets, candidate_rows = base.build_daily_targets(
        events,
        ranking="seal_strength",
    )
    control_targets, control_rows = base.build_daily_targets(
        events,
        ranking="amount",
    )
    selected_symbols = sorted(
        set(candidate_rows["ts_code"].astype(str))
        | set(control_rows["ts_code"].astype(str))
    )
    bars, calendar = base.load_m0_bars(
        paths.base_market_path,
        selected_symbols,
        as_of_date,
    )
    bars = apply_open_point_in_time_limits(bars)
    benchmark_panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [base.BENCHMARK],
        start_date=base.STUDY_START,
        end_date=as_of_date,
    )
    benchmark = benchmark_panel.adjusted_close[base.BENCHMARK].astype(float)
    benchmark = benchmark / float(benchmark.iloc[0])
    target_sets = {
        EXPERIMENT_ID: candidate_targets,
        CONTROL_ID: control_targets,
        STRESS_ID: candidate_targets,
    }
    runs = {
        strategy_id: run_risk_layer_backtest(
            strategy_id,
            "FIXED",
            targets,
            bars,
            calendar,
            benchmark,
            base._execution_model(
                30.0 if strategy_id == STRESS_ID else 10.0
            ),
        )
        for strategy_id, targets in target_sets.items()
    }
    periods = {
        name: (start, as_of_date if end == "LATEST" else end)
        for name, (start, end) in base.PERIODS.items()
    }
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual_all = build_annual_metrics(runs, benchmark, as_of_date)
    annual = {
        year: item
        for year, item in annual_all[EXPERIMENT_ID].items()
        if year >= base.STUDY_START[:4]
    }
    diagnostics = base.build_diagnostics(
        paths,
        runs[EXPERIMENT_ID],
        candidate_targets,
        candidate_rows,
        calendar,
    )
    signal_days = sum(
        date.strftime("%Y%m%d") < as_of_date
        for date in calendar
    )
    active_days = sum(
        bool(weights) and date < as_of_date
        for date, weights in candidate_targets.items()
    )
    diagnostics["signal_days"] = signal_days
    diagnostics["active_signal_share"] = (
        active_days / signal_days if signal_days else 0.0
    )
    diagnostics["failed_order_reasons"] = dict(
        Counter(
            item["reason"]
            for item in runs[EXPERIMENT_ID].result.failed_orders
        )
    )
    gate_metrics = {
        base.EXPERIMENT_ID: metrics[EXPERIMENT_ID],
        base.AMOUNT_CONTROL_ID: metrics[CONTROL_ID],
        base.STRESS_ID: metrics[STRESS_ID],
    }
    gate = base.evaluate_gate(gate_metrics, annual, diagnostics)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "period": [base.STUDY_START, as_of_date],
        "selected_symbol_count": len(selected_symbols),
        "period_metrics": metrics[EXPERIMENT_ID],
        "full_comparison": {
            EXPERIMENT_ID: metrics[EXPERIMENT_ID]["full"],
            CONTROL_ID: metrics[CONTROL_ID]["full"],
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
    return result, runs, {
        EXPERIMENT_ID: candidate_targets,
        CONTROL_ID: control_targets,
    }


def apply_open_point_in_time_limits(bars: pd.DataFrame) -> pd.DataFrame:
    """开盘委托只使用开盘时已经可见的涨跌停状态。"""
    result = bars.copy()
    open_price = pd.to_numeric(result["open"], errors="coerce")
    high = pd.to_numeric(result["high"], errors="coerce")
    low = pd.to_numeric(result["low"], errors="coerce")
    result["limit_up"] = (
        result["limit_up"].fillna(False).astype(bool)
        & open_price.sub(high).abs().le(1e-6)
    )
    result["limit_down"] = (
        result["limit_down"].fillna(False).astype(bool)
        & open_price.sub(low).abs().le(1e-6)
    )
    return result


def _require_audit_passed(paths: RuntimePaths) -> None:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        AUDIT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("首板开盘执行口径审计尚未成功完成")
    if latest.get("outcome") != "PASSED_EXECUTION_AUDIT":
        raise RuntimeError("首板开盘执行口径审计未通过")


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
    targets_path = attempt.output_dir / "daily_targets.csv"
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
        (EXPERIMENT_ID, "首板封单强度前10（开盘时点）"),
        (CONTROL_ID, "首板成交额前10（开盘时点）"),
    ]:
        nav = runs[series_id].result.daily_values.astype(float)
        normalized = nav / float(nav.iloc[0])
        series_rows.extend(
            {
                "series_id": series_id,
                "series_name": series_name,
                "trade_date": date.strftime("%Y%m%d"),
                "nav": float(value),
                "adjust_policy": "qfq_open_point_in_time_t1_10bps",
            }
            for date, value in normalized.items()
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
            "首板开盘可执行复核通过冻结门槛，仅允许继续研究"
            if passed
            else f"首板开盘可执行复核未通过门槛（{', '.join(failed)}），归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "首板开盘可执行复核报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("daily_targets", targets_path, "每日目标组合"),
            ExperimentArtifact("diagnostics", diagnostics_path, "执行诊断"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['annual_turnover']:.1f}x |"
        for name, item in result["period_metrics"].items()
    )
    annual = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    diagnostics = result["diagnostics"]
    return f"""# 首板封单强度开盘可执行复核 V1

- 区间：{result['period'][0]} 至 {result['period'][1]}
- 组合定义保持首轮不变；唯一修正是开盘委托只在开盘已经封住涨跌停时拦截。
- 该修正由独立执行审计触发，参数在修正后收益加载前冻结。
- 本结果仍仅用于研究，不自动注册生产策略。

| 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
{periods}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 执行诊断

- 成交：{diagnostics['trade_count']}；失败委托：{diagnostics['failed_order_count']}
- 失败率：{diagnostics['failed_order_rate']:.2%}
- 失败原因：`{json.dumps(diagnostics['failed_order_reasons'], ensure_ascii=False)}`
- 最差单日：{diagnostics['worst_day']:.2%}
- 95% Expected Shortfall：{diagnostics['expected_shortfall_95']:.2%}
- 与 Quality 相关性：{diagnostics['quality_correlation']:.3f}

## 冻结门槛

{checks}

结论：{'通过研究门槛，但不进入生产' if result['gate']['passed'] else '未通过研究门槛，归档且不注册'}。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=base.RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
