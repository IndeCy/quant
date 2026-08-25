"""
统一行情数据字段约定

该模块只定义轻量级日频行情 schema，避免各数据源在回测链路中使用不同字段名。
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd


TRADE_DATE = "trade_date"
CODE = "code"
SYMBOL = "symbol"
OPEN = "open"
HIGH = "high"
LOW = "low"
CLOSE = "close"
VOLUME = "volume"
AMOUNT = "amount"
IS_SUSPENDED = "is_suspended"
LIMIT_UP = "limit_up"
LIMIT_DOWN = "limit_down"
ADJ_FACTOR = "adj_factor"

PRICE_COLUMNS = [OPEN, HIGH, LOW, CLOSE]
DAILY_BAR_COLUMNS = [
    TRADE_DATE,
    CODE,
    SYMBOL,
    OPEN,
    HIGH,
    LOW,
    CLOSE,
    VOLUME,
    AMOUNT,
    IS_SUSPENDED,
    LIMIT_UP,
    LIMIT_DOWN,
    ADJ_FACTOR,
]

DATE_ALIASES = {"date": TRADE_DATE, "trade_time": TRADE_DATE, "datetime": TRADE_DATE}
SYMBOL_ALIASES = {"ts_code": SYMBOL, "ticker": SYMBOL}


def standardize_daily_bar_schema(df: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
    """
    将外部日K数据统一成项目内部字段。

    返回值使用 trade_date 作为 DatetimeIndex，保留额外字段，便于后续风控或调试。
    """
    if df.empty:
        return pd.DataFrame(columns=[col for col in DAILY_BAR_COLUMNS if col != TRADE_DATE])

    result = df.copy()
    rename_map = {
        column: DATE_ALIASES.get(str(column), SYMBOL_ALIASES.get(str(column), str(column)))
        for column in result.columns
    }
    result = result.rename(columns=rename_map)

    if TRADE_DATE not in result.columns:
        if isinstance(result.index, pd.DatetimeIndex):
            result[TRADE_DATE] = result.index
        else:
            result[TRADE_DATE] = pd.to_datetime(result.index)
    result[TRADE_DATE] = pd.to_datetime(result[TRADE_DATE]).dt.normalize()

    if symbol:
        result[SYMBOL] = result.get(SYMBOL, symbol)
        result[CODE] = result.get(CODE, symbol)
    else:
        if SYMBOL not in result.columns and CODE in result.columns:
            result[SYMBOL] = result[CODE]
        if CODE not in result.columns and SYMBOL in result.columns:
            result[CODE] = result[SYMBOL]

    defaults: dict[str, object] = {
        VOLUME: 0.0,
        AMOUNT: 0.0,
        IS_SUSPENDED: False,
        LIMIT_UP: False,
        LIMIT_DOWN: False,
        ADJ_FACTOR: 1.0,
    }
    for column, default in defaults.items():
        if column not in result.columns:
            result[column] = default

    # 数值字段统一转为数值类型，非法内容转 NaN，由清洗层打标。
    for column in [*PRICE_COLUMNS, VOLUME, AMOUNT, ADJ_FACTOR]:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")

    for column in [IS_SUSPENDED, LIMIT_UP, LIMIT_DOWN]:
        result[column] = result[column].fillna(False).astype(bool)

    result = result.set_index(TRADE_DATE).sort_index()
    result.index.name = TRADE_DATE
    return result


def ordered_daily_bar_columns(existing_columns: Iterable[str]) -> list[str]:
    """按统一 schema 优先排序，同时保留调用方传入的扩展字段。"""
    existing = list(existing_columns)
    ordered = [column for column in DAILY_BAR_COLUMNS if column != TRADE_DATE and column in existing]
    ordered.extend(column for column in existing if column not in ordered)
    return ordered
