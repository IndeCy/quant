"""涨停首板按封单强度选前10、次日开盘轮换的固定事件策略研究。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.adjustment import AdjustType
from data.duckdb_source import DuckDBAshareDataSource
from data.fund_portfolio import load_fund_portfolio_panel
from examples import global_defensive_equal_study as global_study
from examples.limit_up_first_board_strategy_report import render_report
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


EXPERIMENT_ID = "limit_up_first_board_seal_strength_v1"
FEASIBILITY_ID = "limit_up_first_board_event_data_feasibility_v1"
REPORT_PATH = Path("docs/research/limit-up-first-board-seal-strength-v1.md")
STUDY_START = "20230101"
RELIABLE_AS_OF = "20260615"
TOP_N = 10
BENCHMARK = "510300.SH"
AMOUNT_CONTROL_ID = "limit_up_first_board_amount_control"
STRESS_ID = "limit_up_first_board_seal_strength_30bps"
FOLD_KEYS = ("2023", "2024", "2025_latest")
PERIODS = {
    "2023": ("20230101", "20231231"),
    "2024": ("20240101", "20241231"),
    "2025_latest": ("20250101", "LATEST"),
    "locked_test": ("20250101", "LATEST"),
    "full": (STUDY_START, "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="涨停首板封单强度次日轮换 V1",
    category="event_strategy",
    hypothesis=(
        "收盘仍封住且封单额相对成交额更强的非ST首板，是否在下一交易日开盘后仍有一个交易日的"
        "可执行延续收益，并优于简单按成交额追逐首板"
    ),
    definition={
        "dependency": FEASIBILITY_ID,
        "period": [STUDY_START, RELIABLE_AS_OF],
        "event": {
            "limit_type": "U",
            "first_board_proxy": "open_times_eq_0",
            "exclude_name_contains": ["ST", "退"],
        },
        "ranking": {
            "primary": "fd_amount_div_amount_desc",
            "tie_breakers": ["first_time_asc", "amount_desc", "ts_code_asc"],
            "top_n": TOP_N,
            "threshold_search": False,
        },
        "portfolio": {
            "weighting": "equal_weight",
            "signal_frequency": "daily_close",
            "execution": "next_trading_day_open",
            "holding": "one_trading_day_until_next_target",
            "empty_event_day": "cash",
            "leverage": 1.0,
        },
        "control": {
            "same_event_pool": True,
            "ranking": "amount_desc",
            "top_n": TOP_N,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 10.0,
            "stress_slippage_bps": 30.0,
            "commission_rate": 0.0003,
            "min_commission": 5.0,
            "stamp_tax_rate": 0.001,
        },
        "evaluation": {
            "periods": PERIODS,
            "full_return_min": 0.10,
            "full_drawdown_floor": -0.30,
            "full_sharpe_min": 0.75,
            "full_calmar_min": 0.35,
            "positive_excess_vs_hs300": True,
            "return_lift_vs_amount_control_min": 0.02,
            "sharpe_lift_vs_amount_control_min": 0.10,
            "positive_folds_min": 2,
            "worst_fold_drawdown_floor": -0.35,
            "median_fold_sharpe_min": 0.55,
            "locked_return_min": 0.08,
            "locked_drawdown_floor": -0.30,
            "locked_sharpe_min": 0.65,
            "positive_years_min": 3,
            "annual_turnover_max": 250.0,
            "stress_return_min": 0.05,
            "stress_sharpe_min": 0.55,
            "failed_order_rate_max": 0.20,
            "active_signal_share_min": 0.90,
            "worst_day_floor": -0.10,
            "expected_shortfall_95_floor": -0.05,
            "quality_correlation_max": 0.50,
        },
        "parameters_fixed_before_return_loading": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "daily_first_board_rotation_v1",
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
        _require_feasibility_passed(paths)
        result, runs, selections = _calculate(paths, normalized_as_of)
        _complete_attempt(attempt, result, runs, selections)
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
    events = _load_events(paths.limit_list_increment_path, as_of_date)
    candidate_targets, candidate_rows = build_daily_targets(
        events,
        ranking="seal_strength",
    )
    control_targets, control_rows = build_daily_targets(
        events,
        ranking="amount",
    )
    selected_symbols = sorted(
        set(candidate_rows["ts_code"].astype(str))
        | set(control_rows["ts_code"].astype(str))
    )
    bars, calendar = load_m0_bars(
        paths.base_market_path,
        selected_symbols,
        as_of_date,
    )
    benchmark_panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [BENCHMARK],
        start_date=STUDY_START,
        end_date=as_of_date,
    )
    benchmark = benchmark_panel.adjusted_close[BENCHMARK].astype(float)
    benchmark = benchmark / float(benchmark.iloc[0])
    target_sets = {
        EXPERIMENT_ID: candidate_targets,
        AMOUNT_CONTROL_ID: control_targets,
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
            _execution_model(
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
        if year >= STUDY_START[:4]
    }
    diagnostics = build_diagnostics(
        paths,
        runs[EXPERIMENT_ID],
        candidate_targets,
        candidate_rows,
        calendar,
    )
    gate = evaluate_gate(metrics, annual, diagnostics)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "period": [STUDY_START, as_of_date],
        "selected_symbol_count": len(selected_symbols),
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
    return result, runs, {
        EXPERIMENT_ID: candidate_targets,
        AMOUNT_CONTROL_ID: control_targets,
    }


def build_daily_targets(
    events: pd.DataFrame,
    *,
    ranking: str,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    frame = events.copy()
    frame["trade_date"] = frame["trade_date"].astype(str)
    frame["name"] = frame["name"].fillna("").astype(str)
    frame = frame[
        frame["limit_type"].eq("U")
        & pd.to_numeric(frame["open_times"], errors="coerce").fillna(-1).eq(0)
        & ~frame["name"].str.contains("ST|退", case=False, regex=True)
    ].copy()
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    frame["fd_amount"] = pd.to_numeric(frame["fd_amount"], errors="coerce").fillna(0.0)
    frame["seal_strength"] = frame["fd_amount"] / frame["amount"].replace(0, pd.NA)
    frame["first_time"] = frame["first_time"].fillna("").astype(str)
    if ranking == "seal_strength":
        sort_columns = [
            "trade_date",
            "seal_strength",
            "first_time",
            "amount",
            "ts_code",
        ]
        ascending = [True, False, True, False, True]
    elif ranking == "amount":
        sort_columns = ["trade_date", "amount", "ts_code"]
        ascending = [True, False, True]
    else:
        raise ValueError(f"unknown ranking: {ranking}")
    selected = (
        frame.dropna(subset=["seal_strength"])
        .sort_values(sort_columns, ascending=ascending)
        .groupby("trade_date", sort=True)
        .head(TOP_N)
        .copy()
    )
    all_dates = sorted(frame["trade_date"].unique().tolist())
    targets = {
        date: {
            symbol: 1.0 / len(symbols)
            for symbol in symbols
        }
        if symbols
        else {}
        for date in all_dates
        for symbols in [
            selected.loc[
                selected["trade_date"].eq(date),
                "ts_code",
            ].astype(str).tolist()
        ]
    }
    return targets, selected


def load_m0_bars(
    base_path: Path,
    symbols: list[str],
    as_of_date: str,
) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    source = DuckDBAshareDataSource(base_path)
    by_symbol = source.get_daily_bars_many(
        symbols,
        start_date=STUDY_START,
        end_date=as_of_date,
        adjust_policy=AdjustType.QFQ,
    )
    frames = []
    for symbol, frame in by_symbol.items():
        if frame.empty:
            continue
        current = frame.copy()
        current["date"] = current.index
        current["symbol"] = symbol
        frames.append(current.reset_index(drop=True))
    if not frames:
        raise ValueError("首板候选M0行情为空")
    bars = pd.concat(frames, ignore_index=True)
    bars = bars.set_index(["date", "symbol"]).sort_index()
    trading_calendar = source.get_trading_calendar(STUDY_START, as_of_date)
    calendar = trading_calendar.trading_days(STUDY_START, as_of_date)
    return bars, calendar


def build_diagnostics(
    paths: RuntimePaths,
    run: RiskLayerRun,
    targets: dict[str, dict[str, float]],
    selected: pd.DataFrame,
    calendar: list[pd.Timestamp],
) -> dict[str, float | int]:
    nav = run.result.daily_values.loc[STUDY_START:].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    drawdown = nav / nav.cummax() - 1.0
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift(fill_value=False)).cumsum()
    lengths = underwater.groupby(groups).sum()
    failed = len(run.result.failed_orders)
    trades = len(run.result.trades)
    signal_days = sum(
        pd.Timestamp(STUDY_START) <= date <= pd.Timestamp(RELIABLE_AS_OF)
        for date in calendar[:-1]
    )
    active = sum(bool(weights) for weights in targets.values())
    return {
        "signal_days": signal_days,
        "active_signal_share": active / signal_days if signal_days else 0.0,
        "unique_selected_symbols": int(selected["ts_code"].nunique()),
        "trade_count": trades,
        "failed_order_count": failed,
        "failed_order_rate": failed / (trades + failed) if trades + failed else 1.0,
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
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    control = metrics[AMOUNT_CONTROL_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    checks = {
        "full_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_075": full["sharpe"] >= 0.75,
        "full_calmar_at_least_035": full["calmar"] >= 0.35,
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
        "median_fold_sharpe_at_least_055": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        )
        >= 0.55,
        "locked_return_at_least_8pct": locked["annualized_return"] >= 0.08,
        "locked_drawdown_within_30pct": locked["max_drawdown"] >= -0.30,
        "locked_sharpe_at_least_065": locked["sharpe"] >= 0.65,
        "at_least_three_positive_years": positive_years >= 3,
        "annual_turnover_below_250x": full["annual_turnover"] <= 250.0,
        "stress_return_at_least_5pct": stress["annualized_return"] >= 0.05,
        "stress_sharpe_at_least_055": stress["sharpe"] >= 0.55,
        "failed_order_rate_at_most_20pct": (
            float(diagnostics["failed_order_rate"]) <= 0.20
        ),
        "active_signal_share_at_least_90pct": (
            float(diagnostics["active_signal_share"]) >= 0.90
        ),
        "worst_day_within_10pct": float(diagnostics["worst_day"]) >= -0.10,
        "expected_shortfall_95_within_5pct": (
            float(diagnostics["expected_shortfall_95"]) >= -0.05
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


def _execution_model(slippage_bps: float) -> ExecutionModel:
    return ExecutionModel(
        commission_rate=0.0003,
        stamp_tax_rate=0.001,
        slippage_bps=slippage_bps,
        min_commission=5.0,
    )


def _load_events(path: Path, as_of_date: str) -> pd.DataFrame:
    with duckdb.connect(str(path), read_only=True) as connection:
        return connection.execute(
            """
            SELECT *
            FROM limit_list_daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date, ts_code
            """,
            [STUDY_START, as_of_date],
        ).fetchdf()


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("首板事件数据可行性实验尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("首板事件数据可行性门禁未通过")


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
        (EXPERIMENT_ID, "首板封单强度前10"),
        (AMOUNT_CONTROL_ID, "首板成交额前10"),
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
            "首板封单强度次日轮换通过冻结门槛，仅允许继续研究"
            if passed
            else f"首板封单强度次日轮换未通过门槛（{', '.join(failed)}），归档且不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "首板事件策略报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("daily_targets", targets_path, "每日目标组合"),
            ExperimentArtifact("diagnostics", diagnostics_path, "执行与门槛诊断"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("fund_history", paths.fund_daily_history_path),
        ("limit_cache", paths.limit_list_increment_path),
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
