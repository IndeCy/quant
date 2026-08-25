"""Quality Balanced Value V1 的缓冲调仓组合研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.quality_balanced_value_robustness_study import _data_version
from examples.quality_factor_study_support import (
    build_period_metrics,
    metric_summary,
    slice_result,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.quality_market_extension import score_quality_market_extension
from portfolio.topn import build_buffered_topn_selections, build_topn_selections
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from runtime.strategy_definition_loader import load_strategy_definition
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


EXPERIMENT_ID = "quality_balanced_value_buffered_v2"
BASELINE_ID = "quality_balanced_value_unbuffered_v1"
REPORT_PATH = Path("docs/research/quality-balanced-value-buffered-v2.md")
STUDY_START = "20150101"
LOCKED_START = "20220101"
TOP_N = 20
EXIT_RANK = 40
PERIODS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "latest"),
    "locked_test": (LOCKED_START, "latest"),
    "full": (STUDY_START, "latest"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality Balanced Value 缓冲调仓 V2",
    category="portfolio_strategy",
    hypothesis="冻结慢速Alpha和快速风险层后，Top20进入Top40退出能否显著降低换手且保留锁定期收益",
    definition={
        "source_strategy": {
            "strategy_id": "quality_balanced_value_v1",
            "factors_unchanged": True,
            "universe_unchanged": True,
            "score_unchanged": True,
        },
        "portfolio": {
            "entry_rank": TOP_N,
            "exit_rank": EXIT_RANK,
            "weight": "equal",
            "rebalance": "monthly",
            "ineligible_exit_immediately": True,
        },
        "risk_overlay": {
            "scheme": "GRID",
            "window": 20,
            "volatility_threshold": 0.45,
            "reduced_exposure": 0.30,
            "frequency": "daily",
            "unchanged": True,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
        },
        "evaluation": {
            "locked_test_start": LOCKED_START,
            "single_preregistered_buffer": True,
            "no_parameter_grid": True,
            "compare_same_signal_unbuffered": True,
            "midcap_style_attribution": "510500_minus_510300_annual",
        },
        "frozen_gate": {
            "full_annual_return": 0.10,
            "full_sharpe": 0.65,
            "full_drawdown": -0.30,
            "locked_annual_return": 0.08,
            "locked_sharpe": 0.55,
            "locked_drawdown": -0.30,
            "turnover_reduction": 0.30,
            "return_drag_max": 0.01,
            "drawdown_worsening_max": 0.02,
            "stress_annual_return": 0.09,
            "stress_sharpe": 0.55,
            "positive_three_year_fold_share": 0.75,
        },
        "decision": "research_only_never_auto_register",
        "methodology_version": "buffered_portfolio_v2_preregistered",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记研究指纹后才物化财务截面并执行回测。"""
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
    """只改变组合缓冲规则，两个候选共享同一份点时分数。"""
    definition = load_strategy_definition("quality_balanced_value_v1")
    instance = definition.to_instance_payload()
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
        raw_candidates = load_annual_quality_candidates(connection)
        filtered = apply_quality_universe_filters(raw_candidates)
        adjusted = attach_report_adjustment_factors(connection, filtered)
        candidates, corporate_action_audit = build_quality_value_lowvol_candidates(adjusted)
        scores = _score_candidates(candidates)
        selections, holdings = _build_selections(scores)
        all_symbols = sorted(
            {
                symbol
                for targets in selections.values()
                for symbols in targets.values()
                for symbol in symbols
            }
        )
        bars = load_feature_bars(connection, all_symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    targets = {
        strategy_id: _equal_weight_targets(mapping)
        for strategy_id, mapping in selections.items()
    }
    runs = {
        strategy_id: _run_candidate(
            strategy_id,
            strategy_targets,
            bars,
            calendar,
            benchmark,
            slippage_bps=5.0,
        )
        for strategy_id, strategy_targets in targets.items()
    }
    stress_run = _run_candidate(
        f"{EXPERIMENT_ID}_20bps",
        targets[EXPERIMENT_ID],
        bars,
        calendar,
        benchmark,
        slippage_bps=20.0,
    )
    periods = {
        name: (start, latest_date if end == "latest" else min(end, latest_date))
        for name, (start, end) in PERIODS.items()
        if start <= latest_date
    }
    period_metrics = build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        benchmark,
        periods,
    )
    stress_metrics = build_period_metrics(
        {"20bps": stress_run.result},
        benchmark,
        {"full": (STUDY_START, latest_date)},
    )["20bps"]["full"]
    annual_metrics = _annual_metrics(runs, benchmark, latest_date)
    turnover_diagnostics = _turnover_diagnostics(selections)
    style_attribution = _style_attribution(
        paths,
        runs,
        benchmark,
        latest_date,
    )
    gate = evaluate_gate(
        buffered=period_metrics[EXPERIMENT_ID],
        baseline=period_metrics[BASELINE_ID],
        stress=stress_metrics,
        turnover=turnover_diagnostics,
    )
    latest_holdings = holdings[
        holdings["strategy_id"].eq(EXPERIMENT_ID)
        & holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
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
        "turnover_diagnostics": turnover_diagnostics,
        "style_attribution": style_attribution,
        "corporate_action_audit": {
            "checked_rows": corporate_action_audit.checked_rows,
            "changed_rows": corporate_action_audit.changed_rows,
            "excluded_rows": corporate_action_audit.excluded_rows,
            "missing_rows": corporate_action_audit.missing_rows,
        },
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "roe",
                "roa",
                "ocf_to_or",
                "earnings_yield",
                "book_yield",
            ]
        ].to_dict("records"),
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def _score_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    """复用冻结的 Quality80% + E/P10% + B/P10% 评分。"""
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_market_extension(
            group,
            {"earnings_yield": 0.10, "book_yield": 0.10},
        )
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    if not frames:
        return candidates.iloc[0:0].copy()
    return pd.concat(frames, ignore_index=True)


def _build_selections(
    scores: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[str]]], pd.DataFrame]:
    """从同一分数构造无缓冲基线和唯一预注册缓冲候选。"""
    baseline, baseline_holdings = build_topn_selections(
        scores,
        "factor_score",
        TOP_N,
    )
    buffered, buffered_holdings = build_buffered_topn_selections(
        scores,
        "factor_score",
        TOP_N,
        EXIT_RANK,
    )
    baseline_holdings["strategy_id"] = BASELINE_ID
    buffered_holdings["strategy_id"] = EXPERIMENT_ID
    return (
        {
            BASELINE_ID: baseline,
            EXPERIMENT_ID: buffered,
        },
        pd.concat([baseline_holdings, buffered_holdings], ignore_index=True),
    )


def _equal_weight_targets(
    selections: dict[str, list[str]],
) -> dict[str, dict[str, float]]:
    return {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in selections.items()
        if symbols
    }


def _run_candidate(
    strategy_id: str,
    targets: dict[str, dict[str, float]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
    *,
    slippage_bps: float,
) -> RiskLayerRun:
    """所有候选复用原策略的日频波动率风险降档。"""
    return run_risk_layer_backtest(
        strategy_id,
        "GRID",
        targets,
        bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=slippage_bps),
        vol_window=20,
        vol_threshold=0.45,
        reduced_exposure=0.30,
    )


def _annual_metrics(
    runs: dict[str, RiskLayerRun],
    benchmark: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, dict[str, float]]]:
    years = range(2015, int(latest_date[:4]) + 1)
    return {
        strategy_id: {
            str(year): metric_summary(
                slice_result(
                    run.result,
                    f"{year}0101",
                    min(f"{year}1231", latest_date),
                ),
                benchmark,
            )
            for year in years
        }
        for strategy_id, run in runs.items()
    }


def _turnover_diagnostics(
    selections: dict[str, dict[str, list[str]]],
) -> dict[str, float]:
    """用目标名单变更率补充成交口径换手。"""
    output: dict[str, float] = {}
    for strategy_id, mapping in selections.items():
        previous: set[str] = set()
        replacement_shares: list[float] = []
        retention_shares: list[float] = []
        for symbols in mapping.values():
            current = set(symbols)
            if previous:
                retained = len(previous.intersection(current))
                retention_shares.append(retained / max(len(previous), 1))
                replacement_shares.append((len(current) - retained) / max(len(current), 1))
            previous = current
        output[f"{strategy_id}_median_replacement_share"] = (
            float(pd.Series(replacement_shares).median())
            if replacement_shares
            else 0.0
        )
        output[f"{strategy_id}_mean_retention_share"] = (
            float(pd.Series(retention_shares).mean())
            if retention_shares
            else 0.0
        )
    return output


def _style_attribution(
    paths: RuntimePaths,
    runs: dict[str, RiskLayerRun],
    hs300: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, float]]:
    """诊断年度收益对中证500相对沪深300价差的暴露。"""
    csi500 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510500.SH",
        end_date=latest_date,
    )
    style = _calendar_returns(csi500).subtract(_calendar_returns(hs300), fill_value=0.0)
    output: dict[str, dict[str, float]] = {}
    for strategy_id, run in runs.items():
        annual = _calendar_returns(run.result.daily_values)
        joined = pd.concat([annual.rename("strategy"), style.rename("style")], axis=1).dropna()
        variance = float(joined["style"].var(ddof=1)) if len(joined) >= 2 else 0.0
        beta = (
            float(joined["strategy"].cov(joined["style"]) / variance)
            if variance > 0
            else 0.0
        )
        output[strategy_id] = {
            "annual_correlation": (
                float(joined["strategy"].corr(joined["style"]))
                if len(joined) >= 2
                else 0.0
            ),
            "annual_beta": beta,
            "year_count": float(len(joined)),
        }
    return output


def _calendar_returns(values: pd.Series) -> pd.Series:
    normalized = values.copy()
    normalized.index = pd.to_datetime(normalized.index)
    return normalized.groupby(normalized.index.year).apply(
        lambda item: float(item.iloc[-1] / item.iloc[0] - 1)
        if len(item) >= 2 and float(item.iloc[0]) != 0
        else 0.0
    )


def evaluate_gate(
    *,
    buffered: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    stress: dict[str, float],
    turnover: dict[str, float],
) -> dict[str, Any]:
    """缓冲方案必须同时满足绝对门槛与同信号基线门槛。"""
    full = buffered["full"]
    locked = buffered["locked_test"]
    baseline_full = baseline["full"]
    baseline_locked = baseline["locked_test"]
    three_year_names = [
        name for name in ("2015_2017", "2018_2020", "2021_2023") if name in buffered
    ]
    positive_fold_share = (
        sum(buffered[name]["annualized_return"] > 0 for name in three_year_names)
        / max(len(three_year_names), 1)
    )
    checks = {
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "locked_annual_return_at_least_8pct": locked["annualized_return"] >= 0.08,
        "locked_sharpe_at_least_055": locked["sharpe"] >= 0.55,
        "locked_drawdown_within_30pct": locked["max_drawdown"] >= -0.30,
        "turnover_reduced_by_at_least_30pct": (
            full["annual_turnover"] <= baseline_full["annual_turnover"] * 0.70
        ),
        "full_return_drag_within_1pct": (
            full["annualized_return"] >= baseline_full["annualized_return"] - 0.01
        ),
        "locked_return_drag_within_1pct": (
            locked["annualized_return"]
            >= baseline_locked["annualized_return"] - 0.01
        ),
        "full_drawdown_worsening_within_2pct": (
            full["max_drawdown"] >= baseline_full["max_drawdown"] - 0.02
        ),
        "locked_drawdown_worsening_within_2pct": (
            locked["max_drawdown"] >= baseline_locked["max_drawdown"] - 0.02
        ),
        "stress_20bps_annual_return_at_least_9pct": (
            stress["annualized_return"] >= 0.09
        ),
        "stress_20bps_sharpe_at_least_055": stress["sharpe"] >= 0.55,
        "positive_three_year_fold_share_at_least_75pct": (
            positive_fold_share >= 0.75
        ),
        "median_monthly_replacement_at_most_25pct": (
            turnover[f"{EXPERIMENT_ID}_median_replacement_share"] <= 0.25
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_three_year_fold_share": positive_fold_share,
        "turnover_reduction": (
            1.0 - full["annual_turnover"] / baseline_full["annual_turnover"]
            if baseline_full["annual_turnover"] > 0
            else 0.0
        ),
    }


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
            "缓冲调仓通过冻结历史门槛，仅允许进入独立前瞻确认"
            if passed
            else "缓冲调仓未通过冻结门槛，不修改现有策略或生产调度"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "缓冲调仓研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新缓冲持仓"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    metrics = result["period_metrics"]
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
            if period not in metrics[strategy_id]:
                continue
            item = metrics[strategy_id][period]
            rows.append(
                f"| {strategy_id} | {period} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2f}x |"
            )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"][EXPERIMENT_ID].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    turnover = result["turnover_diagnostics"]
    style = result["style_attribution"]
    stress = result["stress_20bps_metrics"]
    return f"""# Quality Balanced Value 缓冲调仓 V2

- 数据截止：{result['latest_date']}。
- Alpha、股票池、月频信号、M0 T+1 和日频风险层均保持不变。
- 唯一改动：Top20进入，已有持仓跌出Top40后退出；没有参数网格。
- 本研究只产生实验记录，不修改生产策略与调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 持仓稳定性

- 原策略月度替换比例中位数：
  {turnover[f'{BASELINE_ID}_median_replacement_share']:.2%}。
- 缓冲策略月度替换比例中位数：
  {turnover[f'{EXPERIMENT_ID}_median_replacement_share']:.2%}。
- 缓冲策略平均持仓保留率：
  {turnover[f'{EXPERIMENT_ID}_mean_retention_share']:.2%}。
- M0成交口径年化换手降幅：
  {result['gate']['turnover_reduction']:.2%}。

## 20bps成本压力

- 年化收益：{stress['annualized_return']:.2%}。
- 最大回撤：{stress['max_drawdown']:.2%}。
- Sharpe：{stress['sharpe']:.3f}。

## 中盘风格诊断

- 原策略对“510500－510300”年度收益相关/Beta：
  {style[BASELINE_ID]['annual_correlation']:.3f} /
  {style[BASELINE_ID]['annual_beta']:.3f}。
- 缓冲策略对“510500－510300”年度收益相关/Beta：
  {style[EXPERIMENT_ID]['annual_correlation']:.3f} /
  {style[EXPERIMENT_ID]['annual_beta']:.3f}。
- 该项仅做归因，不因缓冲组合预期外地承担风格中性化功能。

## 缓冲策略年度表现

| 年份 | 年化收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 预注册门槛

{checks}

结论：{result['decision']}。
"""


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        indicator=paths.fina_indicator_path,
        income=paths.income_statement_path,
        balance=paths.balance_sheet_path,
        cashflow=paths.cashflow_statement_path,
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
