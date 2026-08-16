"""近五日弱封单跌停股票的周频反转固定回测。"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples import global_defensive_equal_study as global_study
from examples import limit_down_weekly_reversal_feasibility_study as feasibility
from examples import limit_up_first_board_open_executable_study as open_execution
from examples import limit_up_first_board_strategy_study as event_base
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


EXPERIMENT_ID = "limit_down_weak_seal_weekly_reversal_v1"
CONTROL_ID = "limit_down_amount_weekly_control"
STRESS_ID = "limit_down_weak_seal_weekly_reversal_30bps"
REPORT_PATH = Path(
    "docs/research/limit-down-weak-seal-weekly-reversal-v1.md"
)
TOP_N = 20
FOLDS = ("2023", "2024", "2025_latest")
PERIODS = {
    "2023": ("20230101", "20231231"),
    "2024": ("20240101", "20241231"),
    "2025_latest": ("20250101", "LATEST"),
    "locked_test": ("20250101", "LATEST"),
    "full": (feasibility.STUDY_START, "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="跌停弱封单周频反转 V1",
    category="event_reversal_strategy",
    hypothesis=(
        "近五个交易日收盘跌停但剩余封单相对成交额较弱的非ST股票，是否代表抛压释放，"
        "在下一周产生可执行反转，并优于简单选择成交额最大的跌停股票"
    ),
    definition={
        "dependency": feasibility.EXPERIMENT_ID,
        "period": [feasibility.STUDY_START, feasibility.RELIABLE_AS_OF],
        "event": {
            "limit_type": "D",
            "lookback_trading_days": 5,
            "exclude_name_contains": ["ST", "退"],
            "latest_event_per_symbol": True,
        },
        "ranking": {
            "primary": "fd_amount_div_amount_ascending",
            "tie_breakers": ["amount_desc", "trade_date_desc", "ts_code_asc"],
            "top_n": TOP_N,
            "threshold_search": False,
        },
        "portfolio": {
            "weight": "equal",
            "signal": "last_trading_day_of_week",
            "execution": "next_trading_day_open",
            "holding": "until_next_weekly_target",
            "empty_week": "cash",
        },
        "control": "same_pool_amount_desc_top20",
        "execution": {
            "model": "M0_open_point_in_time",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 10.0,
            "stress_slippage_bps": 30.0,
            "commission_rate": 0.0003,
            "min_commission": 5.0,
            "stamp_tax_rate": 0.001,
        },
        "evaluation": {
            "periods": PERIODS,
            "full_return_min": 0.08,
            "full_drawdown_floor": -0.35,
            "full_sharpe_min": 0.55,
            "positive_excess_vs_hs300": True,
            "return_lift_vs_amount_control_min": 0.02,
            "sharpe_lift_vs_amount_control_min": 0.10,
            "positive_folds_min": 2,
            "worst_fold_drawdown_floor": -0.35,
            "median_fold_sharpe_min": 0.40,
            "locked_return_min": 0.08,
            "locked_drawdown_floor": -0.30,
            "locked_sharpe_min": 0.55,
            "annual_turnover_max": 70.0,
            "stress_return_min": 0.05,
            "stress_sharpe_min": 0.40,
            "failed_order_rate_max": 0.20,
            "worst_day_floor": -0.12,
            "expected_shortfall_95_floor": -0.06,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_return_loading": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "limit_down_weekly_reversal_v1",
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
        feasibility.RELIABLE_AS_OF,
    )
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
        require_feasibility_passed(paths)
        result, runs, targets = calculate(paths, normalized_as_of)
        complete_attempt(attempt, result, runs, targets)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    dict[str, Any],
    dict[str, RiskLayerRun],
    dict[str, dict[str, dict[str, float]]],
]:
    events = feasibility.load_events(
        paths.limit_list_increment_path,
        as_of_date,
    )
    calendar_text = feasibility.load_calendar(
        paths.base_market_path,
        as_of_date,
    )
    signal_dates = feasibility.weekly_signal_dates(calendar_text)
    candidates = feasibility.build_weekly_candidates(
        events,
        signal_dates,
        calendar_text,
    )
    candidate_targets, selected = build_targets(candidates, "weak_seal")
    control_targets, control_selected = build_targets(candidates, "amount")
    symbols = sorted(
        set(selected["ts_code"].astype(str))
        | set(control_selected["ts_code"].astype(str))
    )
    bars, calendar = event_base.load_m0_bars(
        paths.base_market_path,
        symbols,
        as_of_date,
    )
    bars = open_execution.apply_open_point_in_time_limits(bars)
    benchmark_panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [event_base.BENCHMARK],
        start_date=feasibility.STUDY_START,
        end_date=as_of_date,
    )
    benchmark = benchmark_panel.adjusted_close[
        event_base.BENCHMARK
    ].astype(float)
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
            event_base._execution_model(
                30.0 if strategy_id == STRESS_ID else 10.0
            ),
        )
        for strategy_id, targets in target_sets.items()
    }
    periods = {
        name: (start, as_of_date if end == "LATEST" else end)
        for name, (start, end) in PERIODS.items()
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
        if year >= feasibility.STUDY_START[:4]
    }
    diagnostics = build_diagnostics(
        paths,
        runs[EXPERIMENT_ID],
        selected,
        signal_dates,
    )
    gate = evaluate_gate(metrics, diagnostics)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "period": [feasibility.STUDY_START, as_of_date],
        "period_metrics": metrics[EXPERIMENT_ID],
        "full_comparison": {
            EXPERIMENT_ID: metrics[EXPERIMENT_ID]["full"],
            CONTROL_ID: metrics[CONTROL_ID]["full"],
        },
        "annual_metrics": annual,
        "diagnostics": diagnostics,
        "gate": gate,
        "latest_holdings": (
            selected[
                selected["signal_date"].eq(selected["signal_date"].max())
            ][
                [
                    "signal_date",
                    "trade_date",
                    "ts_code",
                    "name",
                    "seal_strength",
                    "amount",
                    "rank",
                ]
            ].to_dict("records")
        ),
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


def build_targets(
    candidates: pd.DataFrame,
    ranking: str,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    frame = candidates.copy()
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0)
    frame["fd_amount"] = pd.to_numeric(
        frame["fd_amount"],
        errors="coerce",
    ).fillna(0)
    frame["seal_strength"] = frame["fd_amount"] / frame["amount"].replace(
        0,
        pd.NA,
    )
    if ranking == "weak_seal":
        columns = [
            "signal_date",
            "seal_strength",
            "amount",
            "trade_date",
            "ts_code",
        ]
        ascending = [True, True, False, False, True]
    elif ranking == "amount":
        columns = ["signal_date", "amount", "trade_date", "ts_code"]
        ascending = [True, False, False, True]
    else:
        raise ValueError(f"unknown ranking: {ranking}")
    selected = (
        frame.dropna(subset=["seal_strength"])
        .sort_values(columns, ascending=ascending)
        .groupby("signal_date", sort=True)
        .head(TOP_N)
        .copy()
    )
    selected["rank"] = selected.groupby("signal_date").cumcount() + 1
    targets = {}
    for signal_date in sorted(frame["signal_date"].unique()):
        symbols = selected.loc[
            selected["signal_date"].eq(signal_date),
            "ts_code",
        ].astype(str).tolist()
        targets[str(signal_date)] = (
            {symbol: 1.0 / len(symbols) for symbol in symbols}
            if symbols
            else {}
        )
    return targets, selected


def build_diagnostics(
    paths: RuntimePaths,
    run: RiskLayerRun,
    selected: pd.DataFrame,
    signal_dates: list[str],
) -> dict[str, Any]:
    nav = run.result.daily_values.loc[feasibility.STUDY_START:].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    drawdown = nav / nav.cummax() - 1.0
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift(fill_value=False)).cumsum()
    lengths = underwater.groupby(groups).sum()
    failed = len(run.result.failed_orders)
    trades = len(run.result.trades)
    return {
        "signal_weeks": len(signal_dates),
        "active_week_share": float(
            selected["signal_date"].nunique() / len(signal_dates)
        ),
        "unique_selected_symbols": int(selected["ts_code"].nunique()),
        "trade_count": trades,
        "failed_order_count": failed,
        "failed_order_rate": failed / (trades + failed) if trades + failed else 1.0,
        "failed_order_reasons": dict(
            Counter(item["reason"] for item in run.result.failed_orders)
        ),
        "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)),
        "worst_day": float(returns.min()),
        "expected_shortfall_95": float(returns[returns.le(threshold)].mean()),
        "max_underwater_days": int(lengths.max()) if len(lengths) else 0,
        "quality_correlation": global_study.load_quality_correlation(paths, run),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    control = metrics[CONTROL_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[name] for name in FOLDS]
    checks = {
        "full_return_at_least_8pct": full["annualized_return"] >= 0.08,
        "full_drawdown_within_35pct": full["max_drawdown"] >= -0.35,
        "full_sharpe_at_least_055": full["sharpe"] >= 0.55,
        "positive_excess_vs_hs300": full["excess_return"] > 0,
        "return_lift_vs_amount_control_at_least_2pct": (
            full["annualized_return"] - control["annualized_return"] >= 0.02
        ),
        "sharpe_lift_vs_amount_control_at_least_010": (
            full["sharpe"] - control["sharpe"] >= 0.10
        ),
        "at_least_two_positive_folds": sum(
            item["annualized_return"] > 0 for item in folds
        )
        >= 2,
        "worst_fold_drawdown_within_35pct": min(
            item["max_drawdown"] for item in folds
        )
        >= -0.35,
        "median_fold_sharpe_at_least_040": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.40,
        "locked_return_at_least_8pct": locked["annualized_return"] >= 0.08,
        "locked_drawdown_within_30pct": locked["max_drawdown"] >= -0.30,
        "locked_sharpe_at_least_055": locked["sharpe"] >= 0.55,
        "annual_turnover_below_70x": full["annual_turnover"] <= 70.0,
        "stress_return_at_least_5pct": stress["annualized_return"] >= 0.05,
        "stress_sharpe_at_least_040": stress["sharpe"] >= 0.40,
        "failed_order_rate_at_most_20pct": diagnostics["failed_order_rate"] <= 0.20,
        "worst_day_within_12pct": diagnostics["worst_day"] >= -0.12,
        "expected_shortfall_95_within_6pct": (
            diagnostics["expected_shortfall_95"] >= -0.06
        ),
        "quality_correlation_at_most_050": (
            abs(diagnostics["quality_correlation"]) <= 0.50
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def require_feasibility_passed(paths: RuntimePaths) -> None:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        feasibility.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("跌停周频数据可行性实验尚未成功")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("跌停周频数据门禁未通过")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, dict[str, float]]],
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame(
        {
            name: run.result.daily_values
            / float(run.result.daily_values.iloc[0])
            for name, run in runs.items()
        }
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    target_path = attempt.output_dir / "weekly_targets.csv"
    pd.DataFrame(
        [
            {
                "strategy_id": name,
                "signal_date": date,
                "symbol": symbol,
                "target_weight": weight,
            }
            for name, strategy_targets in targets.items()
            for date, weights in strategy_targets.items()
            for symbol, weight in weights.items()
        ]
    ).to_csv(target_path, index=False)
    diagnostic_path = attempt.output_dir / "diagnostics.json"
    diagnostic_path.write_text(
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
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "跌停弱封单周频反转通过冻结门槛，仅允许继续研究"
            if passed
            else "跌停弱封单周频反转未通过冻结门槛，归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "跌停周频反转报告"),
            ExperimentArtifact("daily_nav", nav_path, "策略与对照净值"),
            ExperimentArtifact("weekly_targets", target_path, "周频目标"),
            ExperimentArtifact("diagnostics", diagnostic_path, "执行诊断"),
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
    d = result["diagnostics"]
    return f"""# 跌停弱封单周频反转 V1

- 区间：{result['period'][0]} 至 {result['period'][1]}
- 每周末从近五日非ST跌停池按剩余封单/成交额由低到高选20只，次周开盘等权。
- 开盘时点 M0、10bps；30bps压力测试；参数未做搜索。

| 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
{periods}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 执行诊断

- 成交/失败：{d['trade_count']} / {d['failed_order_count']}
- 失败率：{d['failed_order_rate']:.2%}
- 失败原因：`{json.dumps(d['failed_order_reasons'], ensure_ascii=False)}`
- 最差单日/ES95：{d['worst_day']:.2%} / {d['expected_shortfall_95']:.2%}
- 与 Quality 相关性：{d['quality_correlation']:.3f}

## 冻结门槛

{checks}

结论：{'通过研究门槛，但不进入生产' if result['gate']['passed'] else '未通过研究门槛，归档且不注册'}。
"""


def _data_version(paths: RuntimePaths) -> str:
    parts = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("limit_cache", paths.limit_list_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("monitoring", paths.monitoring_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=feasibility.RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
