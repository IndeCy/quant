"""本地标准行情缓存的只读查询门面。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pandas as pd

from data.adjustment import normalize_adjust_value
from data.cleaning import clean_daily_bars


EMPTY_BAR_COLUMNS = ["open", "high", "low", "close", "volume", "amount"]


def read_cached_daily_bars(
    cache_path: Path,
    provider: str,
    symbol: str,
    frequency: str,
    adjust: str,
    start_date: date = date(2000, 1, 1),
    end_date: date | None = None,
) -> pd.DataFrame:
    """用 SQLite 只读连接加载一段已缓存日线，不初始化或修改缓存 Schema。"""
    if not cache_path.exists():
        return pd.DataFrame(columns=EMPTY_BAR_COLUMNS)
    normalized_adjust = normalize_adjust_value(adjust)
    last_date = end_date or date.today()
    with sqlite3.connect(f"file:{cache_path.resolve()}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT trade_time, open, high, low, close, volume, amount
            FROM market_ohlcv_bar
            WHERE provider = ? AND symbol = ? AND frequency = ? AND adjust = ?
              AND trade_time >= ? AND trade_time <= ?
            ORDER BY trade_time
            """,
            [
                provider,
                symbol,
                frequency,
                normalized_adjust,
                start_date.isoformat(),
                last_date.isoformat(),
            ],
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=EMPTY_BAR_COLUMNS)
    frame = pd.DataFrame([dict(row) for row in rows])
    frame["trade_time"] = pd.to_datetime(frame["trade_time"])
    return clean_daily_bars(frame.set_index("trade_time"), symbol=symbol)

