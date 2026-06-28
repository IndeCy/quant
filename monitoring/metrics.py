"""策略观测指标计算。"""

from __future__ import annotations

import math

import pandas as pd


def build_strategy_monitor_frame(
    strategy_id: str,
    strategy_name: str,
    daily_values: pd.Series,
    benchmark_values: pd.Series | None = None,
    exposure: pd.Series | None = None,
    total_cost: float = 0.0,
    failed_order_count: int = 0,
    turnover_notional: float = 0.0,
    benchmark_id: str = "510300",
    volatility_windows: tuple[int, ...] = (20, 60),
) -> pd.DataFrame:
    """把净值序列转换为 Dashboard 可直接展示的日频指标。"""
    values = _normalize_series(daily_values)
    if values.empty:
        return pd.DataFrame()

    nav = values / float(values.iloc[0])
    daily_return = nav.pct_change().fillna(0.0)
    cumulative_return = nav - 1.0
    drawdown = nav / nav.cummax() - 1.0
    result = pd.DataFrame(
        {
            "trade_date": [date.strftime("%Y%m%d") for date in nav.index],
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "nav": nav.astype(float).values,
            "daily_return": daily_return.astype(float).values,
            "cumulative_return": cumulative_return.astype(float).values,
            "benchmark_id": benchmark_id,
            "drawdown": drawdown.astype(float).values,
            "max_drawdown": drawdown.cummin().astype(float).values,
            "total_execution_cost": float(total_cost),
            "failed_order_count": int(failed_order_count),
            "turnover_notional": float(turnover_notional),
        },
        index=nav.index,
    )

    benchmark_nav = _align_benchmark_nav(benchmark_values, nav.index)
    result["benchmark_nav"] = benchmark_nav.values
    result["benchmark_return"] = benchmark_nav.pct_change().fillna(0.0).values
    result["excess_return"] = result["cumulative_return"] - (benchmark_nav - 1.0).values

    exposure_series = _align_exposure(exposure, nav.index)
    result["exposure"] = exposure_series.values

    for window in volatility_windows:
        result[f"volatility_{window}"] = _rolling_volatility(daily_return, window).values
    if "volatility_20" not in result.columns:
        result["volatility_20"] = _rolling_volatility(daily_return, 20).values
    if "volatility_60" not in result.columns:
        result["volatility_60"] = _rolling_volatility(daily_return, 60).values
    result["sharpe_rolling"] = _rolling_sharpe(daily_return, 60).values

    return result.reset_index(drop=True)


def build_market_monitor_frame(
    benchmark_id: str,
    benchmark_values: pd.Series,
    breadth: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """构建大盘监控指标，宽度数据缺失时保守填0。"""
    values = _normalize_series(benchmark_values)
    if values.empty:
        return pd.DataFrame()
    nav = values / float(values.iloc[0])
    returns = nav.pct_change().fillna(0.0)
    drawdown = nav / nav.cummax() - 1.0
    ma60 = nav.rolling(60, min_periods=1).mean()
    ma120 = nav.rolling(120, min_periods=1).mean()
    frame = pd.DataFrame(
        {
            "trade_date": [date.strftime("%Y%m%d") for date in nav.index],
            "benchmark_id": benchmark_id,
            "benchmark_nav": nav.values,
            "benchmark_return": returns.values,
            "benchmark_drawdown": drawdown.values,
            "ma60": ma60.values,
            "ma120": ma120.values,
            "trend_state": ["UP" if ma60.loc[date] >= ma120.loc[date] else "RISK" for date in nav.index],
        },
        index=nav.index,
    )
    if breadth is not None and not breadth.empty:
        extra = breadth.copy()
        if "trade_date" in extra.columns:
            extra.index = pd.to_datetime(extra["trade_date"], format="%Y%m%d")
        frame = frame.join(extra.drop(columns=["trade_date"], errors="ignore"), how="left")
    for column in ["breadth_up_count", "breadth_down_count", "limit_up_count", "limit_down_count"]:
        if column not in frame.columns:
            frame[column] = 0
        frame[column] = frame[column].fillna(0).astype(int)
    return frame.reset_index(drop=True)


def _normalize_series(series: pd.Series | None) -> pd.Series:
    """清洗时间序列，统一为日期索引和浮点值。"""
    if series is None or series.empty:
        return pd.Series(dtype=float)
    result = pd.Series(series).dropna().astype(float)
    result.index = pd.to_datetime(result.index).normalize()
    return result.sort_index()


def _align_benchmark_nav(benchmark_values: pd.Series | None, index: pd.DatetimeIndex) -> pd.Series:
    """对齐基准净值，缺失时用1表示无基准。"""
    benchmark = _normalize_series(benchmark_values)
    if benchmark.empty:
        return pd.Series(1.0, index=index)
    aligned = benchmark.reindex(index).ffill().bfill()
    return aligned / float(aligned.iloc[0])


def _align_exposure(exposure: pd.Series | None, index: pd.DatetimeIndex) -> pd.Series:
    """仓位按已知最近状态向后延续。"""
    if exposure is None or exposure.empty:
        return pd.Series(1.0, index=index)
    result = _normalize_series(exposure).reindex(index).ffill().fillna(1.0)
    return result.clip(lower=0.0, upper=1.0)


def _rolling_volatility(returns: pd.Series, window: int) -> pd.Series:
    """滚动年化波动率，样本不足时输出0。"""
    return returns.rolling(window, min_periods=2).std(ddof=1).fillna(0.0) * math.sqrt(252)


def _rolling_sharpe(returns: pd.Series, window: int) -> pd.Series:
    """滚动夏普，分母为0时置0。"""
    mean = returns.rolling(window, min_periods=2).mean() * 252
    volatility = _rolling_volatility(returns, window)
    ratio = mean / volatility.mask(volatility == 0)
    return ratio.fillna(0.0).astype(float)
