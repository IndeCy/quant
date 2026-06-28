"""
信号与组合结构解耦分析。

该模块只做事后分析，不参与策略生成、组合构建或成交执行。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.holding_lifecycle import HoldingPeriod, build_holding_periods


@dataclass(frozen=True)
class AlphaDecomposition:
    """entry / holding / exit alpha 拆解结果。"""

    entry_alpha: float
    holding_alpha: float
    exit_alpha: float
    sample_count: int


def forward_return(prices: pd.DataFrame, symbol: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> float | None:
    """计算单只股票从 start 到 end 的前复权收益。"""
    if symbol not in prices.columns:
        return None
    series = prices[symbol].dropna()
    if series.empty:
        return None
    start_candidates = series.loc[series.index >= start_date]
    end_candidates = series.loc[series.index <= end_date]
    if start_candidates.empty or end_candidates.empty:
        return None
    start_price = float(start_candidates.iloc[0])
    end_price = float(end_candidates.iloc[-1])
    if start_price <= 0:
        return None
    return end_price / start_price - 1


def benchmark_return(benchmark_curve: pd.Series, start_date: pd.Timestamp, end_date: pd.Timestamp) -> float | None:
    """计算市场代理收益。"""
    series = benchmark_curve.dropna()
    start_candidates = series.loc[series.index >= start_date]
    end_candidates = series.loc[series.index <= end_date]
    if start_candidates.empty or end_candidates.empty:
        return None
    start_value = float(start_candidates.iloc[0])
    end_value = float(end_candidates.iloc[-1])
    if start_value <= 0:
        return None
    return end_value / start_value - 1


def mean_or_zero(values: list[float]) -> float:
    """空样本返回 0。"""
    return float(sum(values) / len(values)) if values else 0.0


def decompose_lifecycle_alpha(
    trades: list[dict] | pd.DataFrame,
    price_matrix: pd.DataFrame,
    benchmark_curve: pd.Series,
    end_date: str | pd.Timestamp,
    short_window_days: int = 21,
) -> AlphaDecomposition:
    """
    使用真实成交生命周期拆解 alpha。

    - entry alpha：买入后 short_window_days 内相对市场代理的收益。
    - holding alpha：从买入 short_window_days 后到卖出日的相对收益。
    - exit alpha：卖出后 short_window_days 内“避免持有”的相对收益，若卖出后标的跑输市场则为正。
    """
    periods = build_holding_periods(trades, end_date=end_date)
    if not periods:
        return AlphaDecomposition(0.0, 0.0, 0.0, 0)

    entry_values: list[float] = []
    holding_values: list[float] = []
    exit_values: list[float] = []
    final_date = pd.Timestamp(end_date).normalize()

    for period in periods:
        entry_end = min(period.start_date + pd.Timedelta(days=short_window_days), period.end_date)
        entry_stock = forward_return(price_matrix, period.symbol, period.start_date, entry_end)
        entry_bench = benchmark_return(benchmark_curve, period.start_date, entry_end)
        if entry_stock is not None and entry_bench is not None:
            entry_values.append(entry_stock - entry_bench)

        holding_start = entry_end
        if period.end_date > holding_start:
            holding_stock = forward_return(price_matrix, period.symbol, holding_start, period.end_date)
            holding_bench = benchmark_return(benchmark_curve, holding_start, period.end_date)
            if holding_stock is not None and holding_bench is not None:
                holding_values.append(holding_stock - holding_bench)

        if not period.is_open:
            exit_end = min(period.end_date + pd.Timedelta(days=short_window_days), final_date)
            if exit_end > period.end_date:
                post_stock = forward_return(price_matrix, period.symbol, period.end_date, exit_end)
                post_bench = benchmark_return(benchmark_curve, period.end_date, exit_end)
                if post_stock is not None and post_bench is not None:
                    # 卖出后若股票相对市场下跌，说明退出贡献为正。
                    exit_values.append(-(post_stock - post_bench))

    return AlphaDecomposition(
        entry_alpha=mean_or_zero(entry_values),
        holding_alpha=mean_or_zero(holding_values),
        exit_alpha=mean_or_zero(exit_values),
        sample_count=len(periods),
    )


def classify_market_regimes(benchmark_curve: pd.Series) -> pd.Series:
    """
    用样本池等权市场代理按年度划分 bull / bear / sideways。

    这只是分析口径，不作为策略信号：
    - 年收益 > 10%：bull
    - 年收益 < -10%：bear
    - 其他：sideways
    """
    yearly = benchmark_curve.groupby(benchmark_curve.index.year)
    labels: dict[int, str] = {}
    for year, group in yearly:
        if len(group) < 2:
            labels[int(year)] = "sideways"
            continue
        ret = float(group.iloc[-1] / group.iloc[0] - 1)
        if ret > 0.10:
            labels[int(year)] = "bull"
        elif ret < -0.10:
            labels[int(year)] = "bear"
        else:
            labels[int(year)] = "sideways"
    return pd.Series(labels, name="regime")


def strategy_returns_by_regime(daily_values: pd.DataFrame, regimes: pd.Series) -> pd.DataFrame:
    """按市场环境统计策略年度表现。"""
    rows = []
    curve = daily_values["total_value"]
    previous = float(curve.iloc[0])
    for year, group in curve.groupby(curve.index.year):
        if len(group) < 1:
            continue
        end_value = float(group.iloc[-1])
        strategy_return = end_value / previous - 1 if previous > 0 else 0.0
        rows.append(
            {
                "year": int(year),
                "regime": regimes.get(int(year), "sideways"),
                "strategy_return": strategy_return,
            }
        )
        previous = end_value
    return pd.DataFrame(rows)


def summarize_regime_returns(daily_values: pd.DataFrame, regimes: pd.Series) -> pd.DataFrame:
    """输出 bull / bear / sideways 下平均收益和胜率。"""
    yearly = strategy_returns_by_regime(daily_values, regimes)
    if yearly.empty:
        return pd.DataFrame(columns=["regime", "average_return", "win_rate", "year_count"])
    return (
        yearly.groupby("regime")["strategy_return"]
        .agg(
            average_return="mean",
            win_rate=lambda values: float((values > 0).mean()),
            year_count="count",
        )
        .reset_index()
    )
