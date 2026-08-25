"""ETF 中频相对强度与独立趋势状态。"""

from __future__ import annotations

import pandas as pd


def weekly_signal_dates(calendar: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """返回每个自然周最后一个实际交易日。"""
    index = pd.DatetimeIndex(calendar).sort_values().unique()
    if index.empty:
        return []
    frame = pd.DataFrame({"trade_date": index})
    iso = frame["trade_date"].dt.isocalendar()
    frame["iso_year"] = iso["year"].astype(int)
    frame["iso_week"] = iso["week"].astype(int)
    return (
        frame.groupby(["iso_year", "iso_week"], sort=True)["trade_date"]
        .max()
        .tolist()
    )


def calculate_relative_strength_states(
    adjusted_close: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    symbols: list[str],
    *,
    momentum_window: int = 20,
    trend_window: int = 60,
) -> pd.DataFrame:
    """只用信号日及以前价格计算动量、均线状态和横截面排名。"""
    if momentum_window <= 0 or trend_window <= momentum_window:
        raise ValueError("windows must satisfy 0 < momentum < trend")
    missing = sorted(set(symbols) - set(adjusted_close.columns))
    if missing:
        raise ValueError(f"adjusted_close missing symbols: {missing}")
    close = adjusted_close[symbols].sort_index().astype(float)
    momentum = close / close.shift(momentum_window) - 1.0
    trend = close.rolling(
        trend_window,
        min_periods=trend_window,
    ).mean()
    rows: list[dict[str, object]] = []
    for signal_date in signal_dates:
        date = pd.Timestamp(signal_date)
        if date not in close.index:
            continue
        daily: list[dict[str, object]] = []
        for symbol in symbols:
            values = (
                close.at[date, symbol],
                momentum.at[date, symbol],
                trend.at[date, symbol],
            )
            if any(pd.isna(value) for value in values):
                continue
            daily.append(
                {
                    "signal_date": date.strftime("%Y%m%d"),
                    "symbol": symbol,
                    "close": float(values[0]),
                    "momentum_20": float(values[1]),
                    "ma60": float(values[2]),
                    "trend_active": bool(
                        values[0] > values[2] and values[1] > 0
                    ),
                }
            )
        ranked = sorted(
            daily,
            key=lambda item: (-float(item["momentum_20"]), str(item["symbol"])),
        )
        for rank, item in enumerate(ranked, start=1):
            rows.append({**item, "rank": rank})
    return pd.DataFrame(rows)
