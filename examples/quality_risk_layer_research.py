"""
Quality Risk Layer Research。

固定 Quality Cleanup Alpha、股票池和月频 Top20 等权，只研究总仓位风险控制。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import load_hs300_benchmark
from examples.quality_cleanup_audit import (
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_portfolio_construction_study import build_target_quantities
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    attach_financial_dbs,
    create_signal_date_table,
)
from examples.strategy_comparison_research import (
    BacktestResearchResult,
    INITIAL_CASH,
    affordable_quantity,
    build_metrics_table,
    create_feature_table,
    format_percent,
    get_bar,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    mark_to_market,
)


REPORT_PATH = Path("reports/quality_risk_layer_research.md")
BENCHMARK_LOOKBACK_START = "20130101"


def volatility_target_exposure(volatility: float) -> float:
    """方案A：按组合过去60日年化波动率控制仓位。"""
    if volatility > 0.50:
        return 0.30
    if volatility > 0.40:
        return 0.50
    return 1.0


def single_threshold_exposure(volatility: float, threshold: float, reduced_exposure: float) -> float:
    """网格研究：超过单一波动率阈值时切换到指定仓位。"""
    return reduced_exposure if volatility > threshold else 1.0


def index_crash_exposure(index_return_20d: float) -> float:
    """方案B：按510300过去20交易日跌幅控制仓位。"""
    if index_return_20d < -0.20:
        return 0.20
    if index_return_20d < -0.15:
        return 0.50
    return 1.0


def drawdown_exposure(drawdown: float) -> float:
    """方案C：按组合净值相对历史高点回撤控制仓位。"""
    if drawdown < -0.30:
        return 0.20
    if drawdown < -0.20:
        return 0.40
    if drawdown < -0.10:
        return 0.70
    return 1.0


def combined_exposure(volatility: float, drawdown: float) -> float:
    """方案D：方案A与方案C同时启用，取更严格仓位。"""
    return min(volatility_target_exposure(volatility), drawdown_exposure(drawdown))


@dataclass
class RiskLayerRun:
    """单个风险层回测结果。"""

    result: BacktestResearchResult
    exposure: pd.Series
    events: pd.DataFrame


def calculate_risk_state(
    scheme: str,
    daily_values: dict[pd.Timestamp, float],
    benchmark_curve: pd.Series,
    date: pd.Timestamp,
    vol_window: int = 60,
    vol_threshold: float | None = None,
    reduced_exposure: float | None = None,
) -> tuple[float, dict[str, float]]:
    """使用截至当日收盘的历史数据计算目标仓位。"""
    values = pd.Series(daily_values).sort_index()
    returns = values.pct_change().dropna().tail(vol_window)
    volatility = float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) >= vol_window else 0.0
    drawdown = float(values.iloc[-1] / values.max() - 1)
    benchmark = benchmark_curve.loc[:date].dropna()
    index_return_20d = float(benchmark.iloc[-1] / benchmark.iloc[-21] - 1) if len(benchmark) >= 21 else 0.0
    if scheme == "A":
        exposure = volatility_target_exposure(volatility)
    elif scheme == "B":
        exposure = index_crash_exposure(index_return_20d)
    elif scheme == "C":
        exposure = drawdown_exposure(drawdown)
    elif scheme == "D":
        exposure = combined_exposure(volatility, drawdown)
    elif scheme == "GRID" and vol_threshold is not None and reduced_exposure is not None:
        exposure = single_threshold_exposure(volatility, vol_threshold, reduced_exposure)
    else:
        exposure = 1.0
    return exposure, {"volatility60": volatility, "drawdown": drawdown, "index_return20": index_return_20d}


def run_risk_layer_backtest(
    name: str,
    scheme: str,
    base_targets: dict[str, dict[str, float]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark_curve: pd.Series,
    execution_model: ExecutionModel,
    vol_window: int = 60,
    vol_threshold: float | None = None,
    reduced_exposure: float | None = None,
) -> RiskLayerRun:
    """在线运行风险层，信号在收盘生成并于下一交易日执行。"""
    cash = INITIAL_CASH
    positions: dict[str, int] = {}
    pending: dict[pd.Timestamp, list[tuple[str, int, pd.Timestamp]]] = {}
    daily_values: dict[pd.Timestamp, float] = {}
    trades = []
    failed_orders = []
    exposure_history: dict[pd.Timestamp, float] = {}
    events = []
    total_cost = 0.0
    turnover_notional = 0.0
    current_quality: dict[str, float] | None = None
    previous_exposure: float | None = None

    for index, date in enumerate(calendar):
        orders = pending.pop(date, [])
        for symbol, quantity, signal_date in sorted(orders, key=lambda item: item[1] > 0):
            bar = get_bar(bars, date, symbol)
            if bar is None:
                failed_orders.append({"date": date, "symbol": symbol, "reason": "missing_bar"})
                continue
            if quantity > 0:
                quantity = affordable_quantity(cash, quantity, bar, execution_model)
                if quantity <= 0:
                    failed_orders.append({"date": date, "symbol": symbol, "reason": "cash_insufficient"})
                    continue
            execution = execution_model.simulate_order(symbol, quantity, bar, date)
            if not execution.success:
                failed_orders.append({"date": date, "symbol": symbol, "reason": execution.reason})
                continue
            cash -= execution.price * execution.quantity + execution.commission + execution.stamp_tax
            positions[symbol] = positions.get(symbol, 0) + execution.quantity
            if positions[symbol] == 0:
                positions.pop(symbol)
            total_cost += execution.total_fee
            turnover_notional += abs(execution.price * execution.quantity)
            trades.append({"strategy": name, "signal_date": signal_date, "date": date, "symbol": symbol, "quantity": execution.quantity, "price": execution.price, "fee": execution.total_fee})

        value = cash + mark_to_market(positions, bars, date)
        daily_values[date] = value
        date_key = date.strftime("%Y%m%d")
        monthly_rebalance = date_key in base_targets
        if monthly_rebalance:
            current_quality = base_targets[date_key]
        exposure, state = calculate_risk_state(
            scheme,
            daily_values,
            benchmark_curve,
            date,
            vol_window,
            vol_threshold,
            reduced_exposure,
        )
        if current_quality is not None:
            exposure_history[date] = exposure
        exposure_changed = previous_exposure is None or exposure != previous_exposure
        if current_quality is not None and (monthly_rebalance or exposure_changed) and index + 1 < len(calendar):
            target_weights = {symbol: weight * exposure for symbol, weight in current_quality.items()}
            targets = build_target_quantities(target_weights, value, bars, date)
            symbols = sorted(set(positions) | set(targets))
            pending[calendar[index + 1]] = [
                (symbol, targets.get(symbol, 0) - positions.get(symbol, 0), date)
                for symbol in symbols
                if targets.get(symbol, 0) != positions.get(symbol, 0)
            ]
            if exposure_changed:
                events.append({"date": date, "exposure": exposure, **state})
        if current_quality is not None:
            previous_exposure = exposure

    result = BacktestResearchResult(
        strategy=name,
        daily_values=pd.Series(daily_values).sort_index(),
        trades=trades,
        failed_orders=failed_orders,
        total_cost=total_cost,
        turnover_notional=turnover_notional,
    )
    return RiskLayerRun(result, pd.Series(exposure_history).sort_index(), pd.DataFrame(events))


def add_comparison(metrics: pd.DataFrame) -> pd.DataFrame:
    """补充平均仓位、收益损失和回撤改善。"""
    result = metrics.copy()
    base = result[result["策略"].eq("Quality Cleanup 原策略")].iloc[0]
    result["年化收益损失"] = base["年化收益"] - result["年化收益"]
    result["回撤改善"] = result["最大回撤"] - base["最大回撤"]
    return result


def format_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化统一指标。"""
    formatted = frame.copy()
    columns = ["年化收益", "最大回撤", "超额收益", "平均仓位", "年化收益损失", "回撤改善"]
    for column in columns:
        formatted[column] = formatted[column].map(format_percent)
    formatted["夏普比率"] = formatted["夏普比率"].map(lambda value: f"{value:.2f}")
    return formatted[["策略", "年化收益", "最大回撤", "夏普比率", "超额收益", "平均仓位", "年化收益损失", "回撤改善"]]


def render_report(metrics: pd.DataFrame, events_2015: pd.DataFrame) -> str:
    """渲染风险层研究报告。"""
    alternatives = metrics[~metrics["策略"].eq("Quality Cleanup 原策略")].copy()
    improved = alternatives[alternatives["回撤改善"] > 0].copy()
    if improved.empty:
        conclusion = "没有方案降低最大回撤。"
    else:
        improved["效率"] = improved["回撤改善"] / improved["年化收益损失"].clip(lower=0.001)
        best = improved.sort_values(["效率", "回撤改善"], ascending=False).iloc[0]
        conclusion = f"收益损失与回撤改善的综合性价比最高的是 `{best['策略']}`。"
    event_display = events_2015.copy()
    for column in ["exposure", "volatility60", "drawdown", "index_return20"]:
        if column in event_display:
            event_display[column] = event_display[column].map(lambda value: f"{value:.2%}")
    return f"""# Quality Risk Layer Research

## 统一结果

{markdown_table(format_metrics(metrics))}

## 2015 股灾期间仓位变化

{markdown_table(event_display)}

## 结论

{conclusion}

所有风险信号均使用当日收盘前可得历史数据，下一交易日执行；Quality Alpha、股票池和月频 Top20 调仓保持不变。
"""


def main() -> None:
    """运行方案A-D研究。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        selections, holdings = build_top20_from_candidates(candidates)
        base_targets = {
            date: {symbol: 1.0 / len(symbols) for symbol in symbols}
            for date, symbols in selections.items()
            if symbols
        }
        calendar = load_calendar(con)
        benchmark, _ = load_hs300_benchmark(
            con,
            BENCHMARK_LOOKBACK_START,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        bars = load_research_bars(con, sorted(holdings["symbol"].unique().tolist()))
        execution_model = ExecutionModel(slippage_bps=5.0)
        schemes = {
            "Quality Cleanup 原策略": "BASE",
            "方案A 组合波动率目标": "A",
            "方案B 指数急跌保护": "B",
            "方案C 组合回撤保护": "C",
            "方案D 波动率+回撤": "D",
        }
        runs = {
            name: run_risk_layer_backtest(name, scheme, base_targets, bars, calendar, benchmark, execution_model)
            for name, scheme in schemes.items()
        }
        metrics = build_metrics_table({name: run.result for name, run in runs.items()}, benchmark)
        metrics["平均仓位"] = metrics["策略"].map(
            {name: float(run.exposure.mean()) for name, run in runs.items()}
        )
        metrics = add_comparison(metrics)
        events = []
        for name, run in runs.items():
            if name == "Quality Cleanup 原策略" or run.events.empty:
                continue
            frame = run.events.copy()
            frame = frame[(frame["date"] >= pd.Timestamp("2015-05-01")) & (frame["date"] <= pd.Timestamp("2015-12-31"))]
            frame.insert(0, "scheme", name)
            events.append(frame)
        events_2015 = pd.concat(events, ignore_index=True) if events else pd.DataFrame()
        REPORT_PATH.write_text(render_report(metrics, events_2015), encoding="utf-8")
        print(metrics[["策略", "年化收益", "最大回撤", "夏普比率", "超额收益", "平均仓位", "年化收益损失", "回撤改善"]].to_string(index=False))
        print(events_2015.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
