"""跨资产独立均线趋势状态。"""

from __future__ import annotations

import pandas as pd


def calculate_independent_trend_states(
    adjusted_close: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    risky_symbols: list[str],
    *,
    fast_window: int = 60,
    slow_window: int = 120,
) -> pd.DataFrame:
    """只用信号日及以前价格判断每个风险资产是否处于上升趋势。"""
    if fast_window <= 0 or slow_window <= fast_window:
        raise ValueError("trend windows must satisfy 0 < fast < slow")
    missing = sorted(set(risky_symbols) - set(adjusted_close.columns))
    if missing:
        raise ValueError(f"adjusted_close missing risky symbols: {missing}")
    close = adjusted_close[risky_symbols].sort_index().astype(float)
    fast = close.rolling(fast_window, min_periods=fast_window).mean()
    slow = close.rolling(slow_window, min_periods=slow_window).mean()
    rows: list[dict[str, object]] = []
    for signal_date in signal_dates:
        date = pd.Timestamp(signal_date)
        if date not in close.index:
            continue
        for symbol in risky_symbols:
            values = (close.at[date, symbol], fast.at[date, symbol], slow.at[date, symbol])
            if any(pd.isna(value) for value in values):
                continue
            rows.append(
                {
                    "signal_date": date.strftime("%Y%m%d"),
                    "symbol": symbol,
                    "close": float(values[0]),
                    "ma60": float(values[1]),
                    "ma120": float(values[2]),
                    "trend_active": bool(values[1] > values[2]),
                }
            )
    return pd.DataFrame(rows)
