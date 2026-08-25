"""月频横截面未来收益标签，只在训练数据构造阶段使用。"""

from __future__ import annotations

import numpy as np
import pandas as pd


LABEL_COLUMNS = [
    "signal_date",
    "symbol",
    "entry_date",
    "exit_signal_date",
    "exit_date",
    "forward_return",
    "forward_rank",
]


def build_forward_monthly_labels(
    open_prices: pd.DataFrame,
    trading_calendar: list[pd.Timestamp],
    signal_dates: list[str],
) -> pd.DataFrame:
    """按 T+1 开盘到下一调仓 T+1 开盘构造未来一个月标签。"""
    _validate_open_prices(open_prices)
    calendar = pd.DatetimeIndex(sorted(pd.Timestamp(value).normalize() for value in trading_calendar))
    signals = [_normalize_date(value) for value in signal_dates]
    if signals != sorted(set(signals)):
        raise ValueError("signal_dates must be unique and sorted")
    price_frame = open_prices.copy()
    price_frame["trade_date"] = price_frame["trade_date"].map(_normalize_date)
    price_frame["open"] = pd.to_numeric(price_frame["open"], errors="coerce")

    periods: list[pd.DataFrame] = []
    for signal_date, exit_signal_date in zip(signals[:-1], signals[1:]):
        entry_date = _next_trading_day(calendar, signal_date)
        exit_date = _next_trading_day(calendar, exit_signal_date)
        entry = price_frame[price_frame["trade_date"].eq(entry_date)][["symbol", "open"]].rename(
            columns={"open": "entry_open"}
        )
        exit_prices = price_frame[price_frame["trade_date"].eq(exit_date)][["symbol", "open"]].rename(
            columns={"open": "exit_open"}
        )
        period = entry.merge(exit_prices, on="symbol", how="outer", validate="one_to_one")
        valid = period["entry_open"].gt(0) & period["exit_open"].gt(0)
        period["forward_return"] = np.where(
            valid,
            period["exit_open"] / period["entry_open"] - 1.0,
            np.nan,
        )
        period["forward_rank"] = period["forward_return"].rank(pct=True, method="average")
        period["signal_date"] = signal_date
        period["entry_date"] = entry_date
        period["exit_signal_date"] = exit_signal_date
        period["exit_date"] = exit_date
        periods.append(period[LABEL_COLUMNS])
    if not periods:
        return pd.DataFrame(columns=LABEL_COLUMNS)
    return pd.concat(periods, ignore_index=True).sort_values(
        ["signal_date", "symbol"], kind="stable"
    ).reset_index(drop=True)


def required_label_price_dates(
    trading_calendar: list[pd.Timestamp],
    signal_dates: list[str],
) -> list[str]:
    """返回构造标签所需的 T+1 交易日集合。"""
    calendar = pd.DatetimeIndex(sorted(pd.Timestamp(value).normalize() for value in trading_calendar))
    signals = [_normalize_date(value) for value in signal_dates]
    dates = {_next_trading_day(calendar, signal_date) for signal_date in signals}
    return sorted(dates)


def _next_trading_day(calendar: pd.DatetimeIndex, date: str) -> str:
    current = pd.Timestamp(date)
    position = int(calendar.searchsorted(current, side="right"))
    if position >= len(calendar):
        raise ValueError(f"no next trading day after {date}")
    return calendar[position].strftime("%Y%m%d")


def _validate_open_prices(frame: pd.DataFrame) -> None:
    missing = [column for column in ["trade_date", "symbol", "open"] if column not in frame.columns]
    if missing:
        raise ValueError(f"open price frame missing columns: {missing}")
    if frame.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("open price frame contains duplicate trade_date/symbol rows")


def _normalize_date(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y%m%d")
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
