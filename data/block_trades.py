"""大宗交易增量缓存与交易日点时溢价门面。"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any, Protocol

import duckdb
import numpy as np
import pandas as pd


BLOCK_TRADE_ASOF_TABLE = "block_trade_premium_asof"
BLOCK_TRADE_FIELDS = "ts_code,trade_date,price,vol,amount,buyer,seller"


class BlockTradeClient(Protocol):
    """声明 Tushare 大宗交易接口能力。"""

    def block_trade(self, **kwargs: Any) -> pd.DataFrame:
        """按交易日期查询大宗交易。"""


class DuckDBConnection(Protocol):
    """声明点时门面使用的最小 DuckDB 能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class BlockTradeSyncResult:
    """一次大宗交易同步结果。"""

    requested_start: str
    requested_end: str
    fetched_rows: int
    stored_rows: int
    api_calls: int


def update_block_trade_cache(
    client: BlockTradeClient,
    database_path: Path,
    *,
    start_date: str,
    end_date: str,
    force_full: bool = False,
    overlap_days: int = 31,
    page_size: int = 1000,
) -> BlockTradeSyncResult:
    """按自然月分页抓取，并原子替换重叠月份的数据。"""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    if overlap_days < 0 or page_size <= 0:
        raise ValueError("overlap_days must be non-negative and page_size positive")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        _init_cache_schema(connection)
        effective_start = start
        if not force_full:
            last_end = _last_requested_end(connection)
            if last_end is not None:
                effective_start = max(start, last_end - timedelta(days=overlap_days))

        fetched_rows = 0
        api_calls = 0
        for month_start, month_end in _month_ranges(effective_start, end):
            pages: list[pd.DataFrame] = []
            offset = 0
            while True:
                raw = client.block_trade(
                    start_date=month_start.strftime("%Y%m%d"),
                    end_date=month_end.strftime("%Y%m%d"),
                    fields=BLOCK_TRADE_FIELDS,
                    limit=page_size,
                    offset=offset,
                )
                api_calls += 1
                pages.append(raw)
                if len(raw) < page_size:
                    break
                offset += len(raw)
            combined = (
                pd.concat(pages, ignore_index=True)
                if pages
                else pd.DataFrame(columns=BLOCK_TRADE_FIELDS.split(","))
            )
            normalized = normalize_block_trade_events(combined)
            fetched_rows += len(normalized)
            _replace_month(
                connection,
                normalized,
                month_start.strftime("%Y%m%d"),
                month_end.strftime("%Y%m%d"),
            )

        connection.execute(
            """
            INSERT INTO block_trade_sync_state(
                state_id, last_requested_end_date, updated_at
            ) VALUES (1, ?, now())
            ON CONFLICT(state_id) DO UPDATE SET
                last_requested_end_date=excluded.last_requested_end_date,
                updated_at=now()
            """,
            [end.strftime("%Y%m%d")],
        )
        stored_rows = int(
            connection.execute("SELECT COUNT(*) FROM block_trade_events").fetchone()[0]
        )
    finally:
        connection.close()
    return BlockTradeSyncResult(
        requested_start=effective_start.strftime("%Y%m%d"),
        requested_end=end.strftime("%Y%m%d"),
        fetched_rows=fetched_rows,
        stored_rows=stored_rows,
        api_calls=api_calls,
    )


def normalize_block_trade_events(frame: pd.DataFrame) -> pd.DataFrame:
    """统一字段，并为源接口缺失的交易身份补稳定重复序号。"""
    required = BLOCK_TRADE_FIELDS.split(",")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"block trade events missing columns: {missing}")
    output_columns = ["event_key", "duplicate_ordinal", *required, "source"]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)

    data = frame[required].copy()
    dates = pd.to_datetime(data["trade_date"], errors="coerce", format="mixed")
    for column in ["price", "vol", "amount"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = (
        data["ts_code"].fillna("").astype(str).str.len().gt(0)
        & dates.notna()
        & data["price"].gt(0)
        & data["vol"].gt(0)
        & data["amount"].gt(0)
        & np.isfinite(data[["price", "vol", "amount"]]).all(axis=1)
    )
    data = data[valid].copy()
    data["trade_date"] = dates[valid].dt.strftime("%Y%m%d")
    data["ts_code"] = data["ts_code"].astype(str).str.strip()
    data["buyer"] = data["buyer"].fillna("").astype(str).str.strip()
    data["seller"] = data["seller"].fillna("").astype(str).str.strip()
    natural_columns = required
    data = data.sort_values(natural_columns, kind="stable").reset_index(drop=True)
    data["duplicate_ordinal"] = data.groupby(
        natural_columns,
        dropna=False,
    ).cumcount()
    data["event_key"] = data.apply(_event_key, axis=1)
    data["source"] = "tushare_block_trade"
    return data[output_columns]


def attach_block_trade_database(
    connection: DuckDBConnection,
    database_path: Path,
) -> None:
    """只读挂载大宗交易缓存。"""
    if not database_path.exists():
        raise FileNotFoundError(f"缺少大宗交易缓存: {database_path.resolve()}")
    escaped = str(database_path.resolve()).replace("'", "''")
    connection.execute(f"ATTACH DATABASE '{escaped}' AS block_trade_db (READ_ONLY)")


def create_block_trade_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日期表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE block_trade_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO block_trade_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_block_trade_premium_asof(
    connection: DuckDBConnection,
    *,
    lookback_days: int = 60,
) -> str:
    """按成交金额聚合信号日前可见的大宗交易相对收盘溢价。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {BLOCK_TRADE_ASOF_TABLE} AS
        WITH priced_events AS (
            SELECT
                e.event_key,
                e.ts_code AS symbol,
                e.trade_date,
                e.price,
                e.vol,
                e.amount,
                e.buyer,
                e.seller,
                f.raw_close,
                e.price / NULLIF(f.raw_close, 0) - 1.0 AS premium
            FROM block_trade_db.block_trade_events e
            JOIN features f
              ON e.ts_code = f.symbol AND e.trade_date = f.trade_date
            WHERE e.price > 0 AND e.amount > 0 AND f.raw_close > 0
        ),
        visible_events AS (
            SELECT d.signal_date, e.*
            FROM block_trade_signal_dates d
            JOIN priced_events e
              ON e.trade_date <= d.signal_date
             AND DATE_DIFF(
                    'day',
                    STRPTIME(e.trade_date, '%Y%m%d'),
                    STRPTIME(d.signal_date, '%Y%m%d')
                 ) BETWEEN 0 AND {lookback_days}
        )
        SELECT
            signal_date,
            symbol,
            MAX(trade_date) AS latest_trade_date,
            SUM(amount) AS total_block_amount,
            COUNT(*) AS event_count,
            SUM(premium * amount) / NULLIF(SUM(amount), 0)
                AS amount_weighted_premium,
            SUM(amount) FILTER(WHERE premium > 0) / NULLIF(SUM(amount), 0)
                AS premium_amount_share
        FROM visible_events
        GROUP BY signal_date, symbol
        """
    )
    return BLOCK_TRADE_ASOF_TABLE


def load_block_trade_premium_snapshot(connection: DuckDBConnection) -> pd.DataFrame:
    """读取已经物化的大宗交易溢价截面。"""
    return connection.execute(
        f"SELECT * FROM {BLOCK_TRADE_ASOF_TABLE} ORDER BY signal_date, symbol"
    ).fetchdf()


def _init_cache_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """初始化事件和增量游标表。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS block_trade_events (
            event_key VARCHAR PRIMARY KEY,
            duplicate_ordinal INTEGER NOT NULL,
            ts_code VARCHAR NOT NULL,
            trade_date VARCHAR NOT NULL,
            price DOUBLE NOT NULL,
            vol DOUBLE NOT NULL,
            amount DOUBLE NOT NULL,
            buyer VARCHAR NOT NULL,
            seller VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS block_trade_sync_state (
            state_id INTEGER PRIMARY KEY,
            last_requested_end_date VARCHAR NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _replace_month(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> None:
    """在事务中替换完整月区间，避免分页顺序变化产生重复。"""
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            "DELETE FROM block_trade_events WHERE trade_date BETWEEN ? AND ?",
            [start_date, end_date],
        )
        if not frame.empty:
            columns = [
                "event_key",
                "duplicate_ordinal",
                "ts_code",
                "trade_date",
                "price",
                "vol",
                "amount",
                "buyer",
                "seller",
                "source",
            ]
            connection.register("_block_trade_batch", frame[columns])
            try:
                connection.execute(
                    f"""
                    INSERT INTO block_trade_events({", ".join(columns)})
                    SELECT {", ".join(columns)} FROM _block_trade_batch
                    """
                )
            finally:
                connection.unregister("_block_trade_batch")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _event_key(row: pd.Series) -> str:
    payload = "|".join(
        str(row[column])
        for column in [
            "ts_code",
            "trade_date",
            "price",
            "vol",
            "amount",
            "buyer",
            "seller",
            "duplicate_ordinal",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_requested_end(connection: duckdb.DuckDBPyConnection) -> date | None:
    row = connection.execute(
        """
        SELECT last_requested_end_date
        FROM block_trade_sync_state
        WHERE state_id = 1
        """
    ).fetchone()
    return _parse_date(row[0]) if row else None


def _month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    current = start
    while current <= end:
        month_end = date(
            current.year,
            current.month,
            monthrange(current.year, current.month)[1],
        )
        ranges.append((current, min(month_end, end)))
        current = month_end + timedelta(days=1)
    return ranges


def _parse_date(value: str) -> date:
    return datetime.strptime(_normalize_date(value), "%Y%m%d").date()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
