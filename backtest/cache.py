"""
本地行情时序缓存模块

缓存模型按“某标的某周期某时间点的一条 OHLCV 数据”存储，避免不同查询区间重复调用外部行情接口。
覆盖区间单独记录并支持合并，防止离散区间被误判成完整覆盖。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Tuple

import pandas as pd


DEFAULT_CACHE_PATH = Path("data/market_cache.sqlite3")
BarFetcher = Callable[[date, date], pd.DataFrame]
CoverageInterval = Tuple[date, date]
DEFAULT_MAX_FETCH_DAYS = 60


def _to_date(value: date | datetime | str | pd.Timestamp) -> date:
    """将外部传入的日期值统一转换成 date，便于做区间计算。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _date_to_str(value: date | datetime | str | pd.Timestamp) -> str:
    """将日期统一存成 YYYY-MM-DD 字符串，保证 SQLite 查询稳定。"""
    return _to_date(value).isoformat()


class MarketDataCache:
    """本地 OHLCV 行情缓存，默认使用项目 data 目录下的 SQLite 文件。"""

    def __init__(self, db_path: Path | str = DEFAULT_CACHE_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        """关闭 SQLite 连接。"""
        self.conn.close()

    def _init_schema(self) -> None:
        """初始化缓存表结构。"""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_ohlcv_bar (
              id integer PRIMARY KEY AUTOINCREMENT,
              provider varchar(50) NOT NULL DEFAULT '',
              symbol varchar(32) NOT NULL DEFAULT '',
              frequency varchar(20) NOT NULL DEFAULT '',
              adjust varchar(20) NOT NULL DEFAULT '',
              trade_time datetime NOT NULL,
              open real NOT NULL DEFAULT 0,
              high real NOT NULL DEFAULT 0,
              low real NOT NULL DEFAULT 0,
              close real NOT NULL DEFAULT 0,
              volume real NOT NULL DEFAULT 0,
              amount real NOT NULL DEFAULT 0,
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(provider, symbol, frequency, adjust, trade_time)
            );

            CREATE TABLE IF NOT EXISTS market_series_coverage (
              id integer PRIMARY KEY AUTOINCREMENT,
              provider varchar(50) NOT NULL DEFAULT '',
              symbol varchar(32) NOT NULL DEFAULT '',
              frequency varchar(20) NOT NULL DEFAULT '',
              adjust varchar(20) NOT NULL DEFAULT '',
              covered_start_time datetime NOT NULL,
              covered_end_time datetime NOT NULL,
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uk_ohlcv_series_time
            ON market_ohlcv_bar(provider, symbol, frequency, adjust, trade_time);

            CREATE INDEX IF NOT EXISTS idx_ohlcv_series_time
            ON market_ohlcv_bar(provider, symbol, frequency, adjust, trade_time);

            CREATE INDEX IF NOT EXISTS idx_coverage_series_time
            ON market_series_coverage(provider, symbol, frequency, adjust, covered_start_time, covered_end_time);
            """
        )
        self.conn.commit()

    def upsert_bars(
        self,
        provider: str,
        symbol: str,
        frequency: str,
        adjust: str,
        bars: pd.DataFrame,
    ) -> None:
        """批量写入或更新 OHLCV 数据。"""
        if bars.empty:
            return

        rows = []
        for index, row in bars.iterrows():
            rows.append(
                (
                    provider,
                    symbol,
                    frequency,
                    adjust,
                    _date_to_str(index),
                    float(row.get("open", 0.0)),
                    float(row.get("high", 0.0)),
                    float(row.get("low", 0.0)),
                    float(row.get("close", 0.0)),
                    float(row.get("volume", 0.0)),
                    float(row.get("amount", 0.0)),
                )
            )

        self.conn.executemany(
            """
            INSERT INTO market_ohlcv_bar (
              provider, symbol, frequency, adjust, trade_time,
              open, high, low, close, volume, amount
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, symbol, frequency, adjust, trade_time)
            DO UPDATE SET
              open = excluded.open,
              high = excluded.high,
              low = excluded.low,
              close = excluded.close,
              volume = excluded.volume,
              amount = excluded.amount,
              modify_time = CURRENT_TIMESTAMP
            """,
            rows,
        )
        self.conn.commit()

    def read_bars(
        self,
        provider: str,
        symbol: str,
        frequency: str,
        adjust: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """从缓存读取指定时间区间的 OHLCV 数据。"""
        rows = self.conn.execute(
            """
            SELECT trade_time, open, high, low, close, volume, amount
            FROM market_ohlcv_bar
            WHERE provider = ?
              AND symbol = ?
              AND frequency = ?
              AND adjust = ?
              AND trade_time >= ?
              AND trade_time <= ?
            ORDER BY trade_time
            """,
            (provider, symbol, frequency, adjust, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()

        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])

        df = pd.DataFrame([dict(row) for row in rows])
        df["trade_time"] = pd.to_datetime(df["trade_time"])
        df = df.set_index("trade_time")
        return df[["open", "high", "low", "close", "volume", "amount"]]

    def get_coverage(
        self,
        provider: str,
        symbol: str,
        frequency: str,
        adjust: str,
    ) -> List[CoverageInterval]:
        """读取某条时间序列已向外部数据源确认过的覆盖区间。"""
        rows = self.conn.execute(
            """
            SELECT covered_start_time, covered_end_time
            FROM market_series_coverage
            WHERE provider = ?
              AND symbol = ?
              AND frequency = ?
              AND adjust = ?
            ORDER BY covered_start_time
            """,
            (provider, symbol, frequency, adjust),
        ).fetchall()
        return [
            (_to_date(row["covered_start_time"]), _to_date(row["covered_end_time"]))
            for row in rows
        ]

    def record_coverage(
        self,
        provider: str,
        symbol: str,
        frequency: str,
        adjust: str,
        start_date: date,
        end_date: date,
    ) -> None:
        """记录并合并某条时间序列已经确认过的覆盖区间。"""
        if start_date > end_date:
            return

        self.conn.execute(
            """
            INSERT INTO market_series_coverage (
              provider, symbol, frequency, adjust, covered_start_time, covered_end_time
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (provider, symbol, frequency, adjust, start_date.isoformat(), end_date.isoformat()),
        )
        self.conn.commit()
        self._merge_coverage(provider, symbol, frequency, adjust)

    def _merge_coverage(self, provider: str, symbol: str, frequency: str, adjust: str) -> None:
        """合并重叠或相邻覆盖区间，保留真实连续水位。"""
        intervals = self.get_coverage(provider, symbol, frequency, adjust)
        if not intervals:
            return

        merged: List[CoverageInterval] = []
        for start, end in intervals:
            if not merged or start > merged[-1][1] + timedelta(days=1):
                merged.append((start, end))
            else:
                prev_start, prev_end = merged[-1]
                merged[-1] = (prev_start, max(prev_end, end))

        self.conn.execute(
            """
            DELETE FROM market_series_coverage
            WHERE provider = ?
              AND symbol = ?
              AND frequency = ?
              AND adjust = ?
            """,
            (provider, symbol, frequency, adjust),
        )
        self.conn.executemany(
            """
            INSERT INTO market_series_coverage (
              provider, symbol, frequency, adjust, covered_start_time, covered_end_time
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (provider, symbol, frequency, adjust, start.isoformat(), end.isoformat())
                for start, end in merged
            ],
        )
        self.conn.commit()


def find_missing_intervals(
    covered: List[CoverageInterval],
    start_date: date,
    end_date: date,
) -> List[CoverageInterval]:
    """根据已覆盖区间计算目标区间内仍需补拉的缺口。"""
    missing: List[CoverageInterval] = []
    cursor = start_date

    for covered_start, covered_end in sorted(covered):
        if covered_end < cursor:
            continue
        if covered_start > end_date:
            break
        if covered_start > cursor:
            missing.append((cursor, min(covered_start - timedelta(days=1), end_date)))
        cursor = max(cursor, covered_end + timedelta(days=1))
        if cursor > end_date:
            break

    if cursor <= end_date:
        missing.append((cursor, end_date))

    return missing


def split_interval(start_date: date, end_date: date, max_days: int) -> List[CoverageInterval]:
    """将大日期区间拆成多个小区间，避免外部行情接口因查询过长断连。"""
    if max_days <= 0:
        raise ValueError("max_days 必须大于0")

    intervals: List[CoverageInterval] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end_date)
        intervals.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return intervals


def load_or_fetch_ohlcv(
    cache: MarketDataCache,
    provider: str,
    symbol: str,
    frequency: str,
    adjust: str,
    start_date: date,
    end_date: date,
    fetcher: BarFetcher,
    max_fetch_days: int = DEFAULT_MAX_FETCH_DAYS,
) -> pd.DataFrame:
    """优先读取缓存，缓存未覆盖时只补拉缺失区间。"""
    missing = find_missing_intervals(
        cache.get_coverage(provider, symbol, frequency, adjust),
        start_date,
        end_date,
    )

    for missing_start, missing_end in missing:
        for chunk_start, chunk_end in split_interval(missing_start, missing_end, max_fetch_days):
            bars = fetcher(chunk_start, chunk_end)
            cache.upsert_bars(provider, symbol, frequency, adjust, bars)
            # 即使接口返回空数据，也记录该区间已确认，避免周末节假日反复补拉。
            cache.record_coverage(provider, symbol, frequency, adjust, chunk_start, chunk_end)

    return cache.read_bars(provider, symbol, frequency, adjust, start_date, end_date)
