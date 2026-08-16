"""Quality核心、盈利事件与固定防守资产的四袖套研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.mixed_asset_execution import MixedAssetExecutionModel
from data.earnings_surprise import (
    EarningsSurprisePaths,
    attach_earnings_surprise_database,
    create_earnings_surprise_signal_date_table,
    materialize_earnings_surprise_asof,
)
from data.fund_portfolio import load_fund_portfolio_panel
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples import quality_defensive_assets_study as defensive_study
from examples import quality_quarterly_lowvol_blend_study as quality_support
from examples.earnings_surprise_data_feasibility_study import (
    load_earnings_surprise_candidates,
)
from examples.earnings_surprise_strategy_study import build_event_targets
from examples.quality_balanced_value_buffered_study import STUDY_START, _data_version
from examples.quality_balanced_value_size_neutral_study import PERIODS, _style_residual
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun
from factors.earnings_surprise import score_earnings_surprise_rank_frame
from portfolio.fixed_sleeve import build_core_scoped_sleeve_targets
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "quality_defensive_event_60_10_15_15_v1"
BASELINE_ID = "quality_defensive_assets_core_scoped_70_15_15_same_snapshot_v3"
EQUITY_ID = "quality_event_equity_6_to_1_same_snapshot_v1"
REPORT_PATH = Path("docs/research/quality-defensive-event-60-10-15-15-v1.md")
QUALITY_WEIGHT = 0.60
EVENT_WEIGHT = 0.10
EQUITY_WEIGHT = QUALITY_WEIGHT + EVENT_WEIGHT
DEFENSIVE_WEIGHTS = {
    defensive_study.GOLD_SYMBOL: 0.15,
    defensive_study.BOND_SYMBOL: 0.15,
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality×盈利事件×黄金国债60/10/15/15 V1",
    category="portfolio_strategy",
    hypothesis="10%盈利事件卫星能否在防守资产控制回撤的同时改善Quality组合的锁定期收益",
    definition={
        "fixed_budget": {
            "quality_balanced_value_v1": QUALITY_WEIGHT,
            "earnings_surprise_event_rank_v2": EVENT_WEIGHT,
            defensive_study.GOLD_SYMBOL: 0.15,
            defensive_study.BOND_SYMBOL: 0.15,
        },
        "event_satellite": {
            "factor": "raw_sue_percentile_rank",
            "event_age_days": 90,
            "top_n": 20,
            "unconstructible_month": "carry_previous_event_target",
            "before_first_constructible": "quality_only_inside_equity_budget",
        },
        "portfolio": {
            "rebalance": "monthly",
            "allocation_grid": False,
            "overlap": "sum_sleeve_weights",
        },
        "risk_overlay": {
            "scope": "entire_70pct_equity_sleeve",
            "window": 20,
            "threshold": 0.45,
            "reduced_equity_exposure": 0.30,
            "defensive_budget_unchanged": True,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq_for_stocks_none_for_funds",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
            "stock_stamp_tax_rate": 0.001,
            "fund_stamp_tax_rate": 0.0,
        },
        "frozen_gate": {
            "full_annual_return_min": 0.10,
            "full_max_drawdown_floor": -0.22,
            "full_sharpe_min": 0.70,
            "full_calmar_min": 0.45,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.40,
            "annual_turnover_max": 8.0,
            "locked_return_vs_defensive_baseline_floor": -0.01,
            "locked_sharpe_at_least_defensive_baseline": True,
            "walk_forward_style_residual_all_checks": True,
            "stress_20bps_annual_return_min": 0.09,
            "stress_20bps_sharpe_min": 0.60,
        },
        "decision": "research_only_never_auto_register",
        "methodology_version": "fixed_four_sleeve_60_10_15_15_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记唯一固定结构，再读取点时数据。"""
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
        result, runs = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun]]:
    """同一行情快照构造基线和四袖套候选。"""
    fund_panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        list(DEFENSIVE_WEIGHTS),
        start_date="20130101",
        end_date=as_of_date,
    )
    latest_date = fund_panel.latest_common_date
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=latest_date,
    )
    try:
        materialize_market_features(connection)
        signal_dates = [
            date
            for date in load_month_end_signal_dates(connection)
            if STUDY_START <= date <= latest_date
        ]
        quality_targets, quality_holdings = quality_support._build_core(
            connection,
            signal_dates,
            paths,
        )
        quality_targets = {
            date: target
            for date, target in quality_targets.items()
            if date in set(signal_dates)
        }
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
        equity_targets, allocation_diagnostics = build_equity_targets(
            signal_dates,
            quality_targets,
            event_targets,
        )
        stock_symbols = sorted(
            {
                symbol
                for targets in (quality_targets, equity_targets)
                for weights in targets.values()
                for symbol in weights
            }
        )
        stock_bars = load_feature_bars(connection, stock_symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = defensive_study._benchmark_curve(paths, latest_date)
    stock_model = ExecutionModel(slippage_bps=5.0)
    mixed_model = MixedAssetExecutionModel(
        set(DEFENSIVE_WEIGHTS),
        slippage_bps=5.0,
    )
    quality_risk = defensive_study._run_candidate(
        f"{BASELINE_ID}_equity_risk",
        quality_targets,
        stock_bars,
        calendar,
        benchmark,
        stock_model,
        risk_overlay=True,
    )
    equity_risk = defensive_study._run_candidate(
        EQUITY_ID,
        equity_targets,
        stock_bars,
        calendar,
        benchmark,
        stock_model,
        risk_overlay=True,
    )
    baseline_targets = build_core_scoped_sleeve_targets(
        quality_targets,
        quality_risk.exposure,
        core_allocation=EQUITY_WEIGHT,
        defensive_weights=DEFENSIVE_WEIGHTS,
    )
    candidate_targets = build_core_scoped_sleeve_targets(
        equity_targets,
        equity_risk.exposure,
        core_allocation=EQUITY_WEIGHT,
        defensive_weights=DEFENSIVE_WEIGHTS,
    )
    bars = pd.concat([stock_bars, fund_panel.bars]).sort_index()
    baseline_run = defensive_study._run_candidate(
        BASELINE_ID,
        baseline_targets,
        bars,
        calendar,
        benchmark,
        mixed_model,
        risk_overlay=False,
    )
    candidate_run = defensive_study._run_candidate(
        EXPERIMENT_ID,
        candidate_targets,
        bars,
        calendar,
        benchmark,
        mixed_model,
        risk_overlay=False,
    )
    stress_run = defensive_study._run_candidate(
        f"{EXPERIMENT_ID}_20bps",
        candidate_targets,
        bars,
        calendar,
        benchmark,
        MixedAssetExecutionModel(set(DEFENSIVE_WEIGHTS), slippage_bps=20.0),
        risk_overlay=False,
    )
    runs = {
        BASELINE_ID: baseline_run,
        EXPERIMENT_ID: candidate_run,
    }
    periods = {
        name: (start, latest_date if end == "latest" else min(end, latest_date))
        for name, (start, end) in PERIODS.items()
        if start <= latest_date
    }
    metrics = build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        benchmark,
        periods,
    )
    stress = build_period_metrics(
        {"20bps": stress_run.result},
        benchmark,
        {"full": (STUDY_START, latest_date)},
    )["20bps"]["full"]
    annual = build_annual_metrics(runs, benchmark, latest_date)
    style = _style_residual(runs, benchmark, _load_csi500(paths, latest_date))
    gate = evaluate_gate(
        candidate=metrics[EXPERIMENT_ID],
        baseline=metrics[BASELINE_ID],
        annual=annual[EXPERIMENT_ID],
        stress=stress,
        residual=style[EXPERIMENT_ID],
    )
    latest_target_date = max(candidate_targets)
    names = (
        quality_holdings[["symbol", "name"]]
        .drop_duplicates("symbol", keep="last")
        .set_index("symbol")["name"]
        .to_dict()
    )
    latest_holdings = [
        {
            "signal_date": latest_target_date,
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "target_weight": weight,
            "sleeve": _holding_sleeve(symbol, latest_target_date, event_targets),
        }
        for symbol, weight in sorted(
            candidate_targets[latest_target_date].items(),
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
        "period_metrics": metrics,
        "annual_metrics": annual,
        "stress_20bps_metrics": stress,
        "style_residual": style,
        "allocation_diagnostics": allocation_diagnostics,
        "event_diagnostics": event_diagnostics,
        "quality_holding_records": len(quality_holdings),
        "event_holding_records": len(event_holdings),
        "latest_holdings": latest_holdings,
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result, runs


def build_equity_targets(
    signal_dates: list[str],
    quality_targets: dict[str, dict[str, float]],
    event_targets: dict[str, dict[str, float]],
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """在70%权益袖套内固定为Quality 6/7、事件1/7。"""
    quality_share = QUALITY_WEIGHT / EQUITY_WEIGHT
    event_share = EVENT_WEIGHT / EQUITY_WEIGHT
    output: dict[str, dict[str, float]] = {}
    current_event: dict[str, float] | None = None
    active_months = 0
    overlaps: list[float] = []
    for signal_date in signal_dates:
        quality = quality_targets.get(signal_date)
        if not quality:
            continue
        if signal_date in event_targets:
            current_event = event_targets[signal_date]
        if current_event is None:
            output[signal_date] = dict(quality)
            continue
        active_months += 1
        target = {
            symbol: weight * quality_share
            for symbol, weight in quality.items()
        }
        for symbol, weight in current_event.items():
            target[symbol] = target.get(symbol, 0.0) + weight * event_share
        output[signal_date] = target
        overlaps.append(
            len(set(quality).intersection(current_event))
            / max(len(current_event), 1)
        )
    return output, {
        "combined_months": float(len(output)),
        "event_active_months": float(active_months),
        "event_active_share": active_months / max(len(output), 1),
        "median_sleeve_symbol_overlap": (
            float(pd.Series(overlaps).median()) if overlaps else 0.0
        ),
    }


def evaluate_gate(
    *,
    candidate: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    stress: dict[str, float],
    residual: dict[str, Any],
) -> dict[str, Any]:
    """绝对风险收益、样本外相对改善、风格残差和成本同时通过。"""
    full = candidate["full"]
    locked = candidate["locked_test"]
    baseline_locked = baseline["locked_test"]
    folds = [
        candidate[key]
        for key in ("2015_2017", "2018_2020", "2021_2023", "2024_latest")
    ]
    checks = {
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_22pct": full["max_drawdown"] >= -0.22,
        "full_sharpe_at_least_070": full["sharpe"] >= 0.70,
        "full_calmar_at_least_045": full["calmar"] >= 0.45,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_25pct": (
            min(item["max_drawdown"] for item in folds) >= -0.25
        ),
        "median_fold_sharpe_at_least_040": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.40
        ),
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "locked_return_within_1pct_of_defensive_baseline": (
            locked["annualized_return"]
            >= baseline_locked["annualized_return"] - 0.01
        ),
        "locked_sharpe_at_least_defensive_baseline": (
            locked["sharpe"] >= baseline_locked["sharpe"]
        ),
        "walk_forward_style_residual_gate_passed": bool(residual["gate_passed"]),
        "stress_20bps_annual_return_at_least_9pct": (
            stress["annualized_return"] >= 0.09
        ),
        "stress_20bps_sharpe_at_least_060": stress["sharpe"] >= 0.60,
        "at_least_nine_positive_years": (
            sum(item["annualized_return"] > 0 for item in annual.values()) >= 9
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _load_csi500(paths: RuntimePaths, latest_date: str) -> pd.Series:
    from data.benchmark_series import load_adjusted_fund_curve

    return load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510500.SH",
        end_date=latest_date,
    )


def _holding_sleeve(
    symbol: str,
    signal_date: str,
    event_targets: dict[str, dict[str, float]],
) -> str:
    if symbol in DEFENSIVE_WEIGHTS:
        return "defensive_asset"
    event_dates = [date for date in event_targets if date <= signal_date]
    if event_dates and symbol in event_targets[max(event_dates)]:
        return "quality_and_or_event"
    return "quality_core"


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
) -> None:
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.concat(
        [
            (run.result.daily_values / float(run.result.daily_values.iloc[0])).rename(
                strategy_id
            )
            for strategy_id, run in runs.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "固定四袖套通过全部门槛，仅进入冻结前瞻确认"
            if passed
            else "固定四袖套未通过全部门槛，不修改生产策略或调度"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "四袖套研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "基线与候选净值"),
            ExperimentArtifact("latest_holdings", holdings_path, "最新组合目标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows: list[str] = []
    for strategy_id in (BASELINE_ID, EXPERIMENT_ID):
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
                f"| {strategy_id} | {period} | "
                f"{item['annualized_return']:.2%} | {item['max_drawdown']:.2%} | "
                f"{item['sharpe']:.3f} | {item['calmar']:.3f} | "
                f"{item['annual_turnover']:.2f}x |"
            )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    residual = result["style_residual"][EXPERIMENT_ID]
    stress = result["stress_20bps_metrics"]
    allocation = result["allocation_diagnostics"]
    return f"""# Quality×盈利事件×黄金国债 60/10/15/15 V1

- 数据截止：{result['latest_date']}。
- 固定预算：Quality 60%、SUE事件 10%、黄金ETF 15%、五年国债ETF 15%。
- 权益袖套统一日频风险层；防守资产预算不随权益风险层缩放。
- 点时财务、股票前复权、基金不复权、M0 T+1；没有权重网格。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 诊断

- 事件有效月份占比：{allocation['event_active_share']:.2%}。
- 两股票袖套代码重叠中位数：
  {allocation['median_sleeve_symbol_overlap']:.2%}。
- 20bps压力年化/Sharpe：
  {stress['annualized_return']:.2%} / {stress['sharpe']:.3f}。
- 锁定期风格Beta/平均残差/最差残差：
  {residual['locked_beta']:.3f} /
  {residual['locked_mean_residual']:.2%} /
  {residual['locked_worst_residual']:.2%}。

## 冻结门槛

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
