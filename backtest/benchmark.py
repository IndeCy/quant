"""
收益基线对比模块

用于把策略资产曲线和基线指数曲线对齐，输出总收益、年化收益、超额收益以及分年度对比。
当前默认业务基线可以是上证指数，但模块本身不绑定具体标的。
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd

from data.cleaning import clean_daily_bars


def _total_return(values: pd.Series) -> float:
    """计算一段资产曲线的总收益率。"""
    if values.empty:
        return 0.0
    return float(values.iloc[-1] / values.iloc[0] - 1)


def _annualized_return(total_return: float, days: int) -> float:
    """按A股252个交易日估算年化收益率。"""
    if days < 2:
        return 0.0
    years = days / 252
    return float((1 + total_return) ** (1 / years) - 1)


def build_benchmark_curve(
    benchmark_bars: pd.DataFrame,
    target_index: pd.Index,
    initial_capital: float,
) -> pd.Series:
    """
    将基线收盘点位对齐为与策略同日期的资产曲线。

    Args:
        benchmark_bars: 基线K线数据，必须包含 close 列。
        target_index: 策略资产曲线日期索引。
        initial_capital: 归一化起始资金。

    Returns:
        Series: 与 target_index 对齐的基线资产曲线。
    """
    if benchmark_bars.empty or len(target_index) == 0:
        return pd.Series(dtype=float, name="benchmark_value")

    benchmark_bars = benchmark_bars.copy()
    if "close" in benchmark_bars.columns:
        for column in ["open", "high", "low"]:
            if column not in benchmark_bars.columns:
                benchmark_bars[column] = benchmark_bars["close"]
    benchmark_bars = clean_daily_bars(benchmark_bars, symbol="BENCHMARK")
    closes = benchmark_bars["close"].copy()
    closes.index = pd.to_datetime(closes.index)
    aligned = closes.reindex(pd.to_datetime(target_index), method="ffill").bfill()
    if aligned.empty or aligned.iloc[0] == 0:
        return pd.Series(dtype=float, name="benchmark_value")

    curve = initial_capital * aligned / aligned.iloc[0]
    curve.name = "benchmark_value"
    return curve


def calculate_return_comparison(
    strategy_daily_values: pd.DataFrame,
    benchmark_bars: pd.DataFrame,
    initial_capital: float,
    benchmark_name: str = "基线",
) -> Dict[str, float | str]:
    """计算策略和基线的总收益、年化收益与超额收益。"""
    if strategy_daily_values.empty:
        return {
            "基线名称": benchmark_name,
            "策略总收益率": 0.0,
            "基线总收益率": 0.0,
            "超额收益率": 0.0,
            "策略年化收益率": 0.0,
            "基线年化收益率": 0.0,
            "年化超额收益率": 0.0,
        }

    strategy_curve = strategy_daily_values["total_value"]
    benchmark_curve = build_benchmark_curve(benchmark_bars, strategy_daily_values.index, initial_capital)
    strategy_return = _total_return(strategy_curve)
    benchmark_return = _total_return(benchmark_curve)
    strategy_annual = _annualized_return(strategy_return, len(strategy_curve))
    benchmark_annual = _annualized_return(benchmark_return, len(benchmark_curve))

    return {
        "基线名称": benchmark_name,
        "策略总收益率": strategy_return,
        "基线总收益率": benchmark_return,
        "超额收益率": strategy_return - benchmark_return,
        "策略年化收益率": strategy_annual,
        "基线年化收益率": benchmark_annual,
        "年化超额收益率": strategy_annual - benchmark_annual,
    }


def calculate_yearly_return_comparison(
    strategy_daily_values: pd.DataFrame,
    benchmark_bars: pd.DataFrame,
    initial_capital: float,
) -> List[Dict[str, float | int | str]]:
    """按自然年计算策略收益、基线收益和超额收益。"""
    if strategy_daily_values.empty:
        return []

    benchmark_curve = build_benchmark_curve(benchmark_bars, strategy_daily_values.index, initial_capital)
    rows: List[Dict[str, float | int | str]] = []
    prev_strategy_value = initial_capital
    prev_benchmark_value = initial_capital

    for year, group in strategy_daily_values.groupby(strategy_daily_values.index.year):
        benchmark_group = benchmark_curve.loc[group.index]
        strategy_end = float(group["total_value"].iloc[-1])
        benchmark_end = float(benchmark_group.iloc[-1])
        strategy_return = strategy_end / prev_strategy_value - 1
        benchmark_return = benchmark_end / prev_benchmark_value - 1
        rows.append(
            {
                "year": int(year),
                "start_date": group.index[0].strftime("%Y-%m-%d"),
                "end_date": group.index[-1].strftime("%Y-%m-%d"),
                "strategy_start_value": prev_strategy_value,
                "strategy_end_value": strategy_end,
                "benchmark_start_value": prev_benchmark_value,
                "benchmark_end_value": benchmark_end,
                "strategy_return": strategy_return,
                "benchmark_return": benchmark_return,
                "excess_return": strategy_return - benchmark_return,
            }
        )
        prev_strategy_value = strategy_end
        prev_benchmark_value = benchmark_end

    return rows
