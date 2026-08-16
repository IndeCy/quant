"""ETF 绝对与相对动量因子。"""

from __future__ import annotations

import pandas as pd


def month_end_signal_dates(calendar: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """返回有下一交易日可执行的月末信号日。"""
    index = pd.DatetimeIndex(calendar).sort_values().unique()
    if len(index) < 2:
        return []
    monthly = pd.Series(index=index, data=index).groupby(index.to_period("M")).max()
    return [pd.Timestamp(value) for value in monthly if value < index[-1]]


def calculate_trailing_momentum(
    adjusted_close: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    risky_symbols: list[str],
    *,
    lookback_days: int = 252,
) -> pd.DataFrame:
    """只使用信号日及以前收盘价计算固定窗口总收益。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    missing = sorted(set(risky_symbols) - set(adjusted_close.columns))
    if missing:
        raise ValueError(f"adjusted_close missing risky symbols: {missing}")
    close = adjusted_close[risky_symbols].sort_index().astype(float)
    momentum = close.pct_change(periods=lookback_days, fill_method=None)
    rows: list[dict[str, object]] = []
    for signal_date in signal_dates:
        date = pd.Timestamp(signal_date)
        if date not in momentum.index:
            continue
        for symbol, value in momentum.loc[date].items():
            if pd.isna(value):
                continue
            rows.append(
                {
                    "signal_date": date.strftime("%Y%m%d"),
                    "symbol": str(symbol),
                    "momentum_252": float(value),
                    "factor_score": float(value),
                }
            )
    return pd.DataFrame(rows)
