"""财务因子研究的区间指标与固定排序工具。"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from examples.strategy_comparison_research import (
    BacktestResearchResult,
    build_metrics_table,
)


def build_period_metrics(
    results: Mapping[str, BacktestResearchResult],
    benchmark: pd.Series,
    periods: Mapping[str, tuple[str, str]],
) -> dict[str, dict[str, dict[str, float]]]:
    """按固定区间切片，避免候选各自实现一套指标口径。"""
    return {
        strategy_id: {
            period: metric_summary(
                slice_result(result, start_date, end_date),
                benchmark,
            )
            for period, (start_date, end_date) in periods.items()
        }
        for strategy_id, result in results.items()
    }


def select_on_validation(
    metrics: Mapping[str, dict[str, dict[str, float]]],
    candidate_ids: set[str],
) -> str:
    """按预先声明的Sharpe、Calmar、回撤、换手和ID稳定排序。"""
    return sorted(
        candidate_ids,
        key=lambda candidate_id: (
            -metrics[candidate_id]["validation"]["sharpe"],
            -metrics[candidate_id]["validation"]["calmar"],
            -metrics[candidate_id]["validation"]["max_drawdown"],
            metrics[candidate_id]["validation"]["annual_turnover"],
            candidate_id,
        ),
    )[0]


def slice_result(
    result: BacktestResearchResult,
    start_date: str,
    end_date: str,
) -> BacktestResearchResult:
    """截取净值、成交与失败委托，保持区间成本和换手一致。"""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    trades = [
        trade
        for trade in result.trades
        if start <= pd.Timestamp(trade["date"]) <= end
    ]
    failures = [
        order
        for order in result.failed_orders
        if start <= pd.Timestamp(order["date"]) <= end
    ]
    return BacktestResearchResult(
        strategy=result.strategy,
        daily_values=result.daily_values.loc[start:end],
        trades=trades,
        failed_orders=failures,
        total_cost=sum(float(trade["fee"]) for trade in trades),
        turnover_notional=sum(
            abs(float(trade["price"]) * int(trade["quantity"]))
            for trade in trades
        ),
    )


def metric_summary(
    result: BacktestResearchResult,
    benchmark: pd.Series,
) -> dict[str, float]:
    """转成研究门槛使用的稳定英文指标结构。"""
    row = build_metrics_table({result.strategy: result}, benchmark).iloc[0]
    annual = float(row["年化收益"])
    drawdown = float(row["最大回撤"])
    return {
        "annualized_return": annual,
        "max_drawdown": drawdown,
        "sharpe": float(row["夏普比率"]),
        "calmar": annual / abs(drawdown) if drawdown < 0 else 0.0,
        "excess_return": float(row["超额收益"]),
        "annual_turnover": float(row["年化换手率"]),
        "trade_count": float(row["交易次数"]),
        "execution_cost_impact": float(row["执行成本影响"]),
    }
