"""重要股东增减持增量缓存与公告日 as-of 门面。"""

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


HOLDER_TRADE_ASOF_TABLE = "holder_trade_signal_asof"
HOLDER_TRADE_FIELDS = ",".join(
    [
        "ts_code",
        "ann_date",
        "holder_name",
        "holder_type",
        "in_de",
        "change_vol",
        "change_ratio",
        "after_share",
        "after_ratio",
        "avg_price",
        "total_share",
        "begin_date",
        "close_date",
    ]
)


class HolderTradeClient(Protocol):
    """声明 Tushare 重要股东增减持接口能力。"""

    def stk_holdertrade(self, **kwargs: Any) -> pd.DataFrame:
        """按公告日期查询重要股东增减持事件。"""


class DuckDBConnection(Protocol):
    """声明 as-of 门面使用的最小 DuckDB 能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class HolderTradeSyncResult:
    """一次增减持事件同步结果。"""

    requested_start: str
    requested_end: str
    fetched_rows: int
    stored_rows: int
    api_calls: int


def update_holder_trade_cache(
    client: HolderTradeClient,
    database_path: Path,
    *,
    start_date: str,
    end_date: str,
    force_full: bool = False,
    overlap_days: int = 31,
    page_size: int = 3000,
) -> HolderTradeSyncResult:
    """按公告月分页更新缓存，并保留历史修订供 as-of 查询。"""
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
            offset = 0
            while True:
                raw = client.stk_holdertrade(
                    start_date=month_start.strftime("%Y%m%d"),
                    end_date=month_end.strftime("%Y%m%d"),
                    fields=HOLDER_TRADE_FIELDS,
                    limit=page_size,
                    offset=offset,
                )
                api_calls += 1
                normalized = normalize_holder_trade_events(raw)
                fetched_rows += len(normalized)
                _upsert_events(connection, normalized)
                if len(raw) < page_size:
                    break
                offset += len(raw)

        connection.execute(
            """
            INSERT INTO holder_trade_sync_state(
                state_id, last_requested_end_date, updated_at
            ) VALUES (1, ?, now())
            ON CONFLICT(state_id) DO UPDATE SET
                last_requested_end_date=excluded.last_requested_end_date,
                updated_at=now()
            """,
            [end.strftime("%Y%m%d")],
        )
        stored_rows = int(
            connection.execute("SELECT COUNT(*) FROM holder_trade_events").fetchone()[0]
        )
    finally:
        connection.close()
    return HolderTradeSyncResult(
        requested_start=effective_start.strftime("%Y%m%d"),
        requested_end=end.strftime("%Y%m%d"),
        fetched_rows=fetched_rows,
        stored_rows=stored_rows,
        api_calls=api_calls,
    )


def normalize_holder_trade_events(frame: pd.DataFrame) -> pd.DataFrame:
    """清洗事件字段，并为同一增减持计划生成稳定身份。"""
    required = [
        "ts_code",
        "ann_date",
        "holder_name",
        "holder_type",
        "in_de",
        "change_vol",
        "change_ratio",
        "after_share",
        "after_ratio",
        "avg_price",
        "total_share",
        "begin_date",
        "close_date",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"holder trade events missing columns: {missing}")
    output_columns = ["event_key", *required, "source"]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)

    data = frame[required].copy()
    ann_dates = pd.to_datetime(data["ann_date"], errors="coerce", format="mixed")
    begin_dates = pd.to_datetime(data["begin_date"], errors="coerce", format="mixed")
    close_dates = pd.to_datetime(data["close_date"], errors="coerce", format="mixed")
    numeric_columns = [
        "change_vol",
        "change_ratio",
        "after_share",
        "after_ratio",
        "avg_price",
        "total_share",
    ]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = (
        data["ts_code"].fillna("").astype(str).str.len().gt(0)
        & data["holder_name"].fillna("").astype(str).str.strip().str.len().gt(0)
        & data["holder_type"].isin(["G", "P", "C"])
        & data["in_de"].isin(["IN", "DE"])
        & ann_dates.notna()
        & data["change_ratio"].gt(0)
        & np.isfinite(data["change_ratio"])
    )
    data = data[valid].copy()
    ann_dates = ann_dates[valid]
    begin_dates = begin_dates[valid]
    close_dates = close_dates[valid]
    data["ann_date"] = ann_dates.dt.strftime("%Y%m%d")
    data["begin_date"] = begin_dates.dt.strftime("%Y%m%d")
    data["close_date"] = close_dates.dt.strftime("%Y%m%d")
    data["ts_code"] = data["ts_code"].astype(str).str.strip()
    data["holder_name"] = data["holder_name"].astype(str).str.strip()
    data["event_key"] = data.apply(_event_key, axis=1)
    data["source"] = "tushare_stk_holdertrade"
    return (
        data[output_columns]
        .sort_values(["event_key", "ann_date"])
        .drop_duplicates(["event_key", "ann_date"], keep="last")
        .reset_index(drop=True)
    )


def attach_holder_trade_database(
    connection: DuckDBConnection,
    database_path: Path,
) -> None:
    """只读挂载重要股东增减持缓存。"""
    if not database_path.exists():
        raise FileNotFoundError(f"缺少重要股东增减持缓存: {database_path.resolve()}")
    escaped = str(database_path.resolve()).replace("'", "''")
    connection.execute(f"ATTACH DATABASE '{escaped}' AS holder_trade_db (READ_ONLY)")


def create_holder_trade_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立研究使用的月末信号日表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE holder_trade_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO holder_trade_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_holder_trade_asof(
    connection: DuckDBConnection,
    *,
    lookback_days: int = 180,
) -> str:
    """聚合信号日前180天可见的高管和个人净增持比例。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {HOLDER_TRADE_ASOF_TABLE} AS
        WITH visible_revisions AS (
            SELECT
                d.signal_date,
                e.*,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, e.event_key
                    ORDER BY e.ann_date DESC, e.fetched_at DESC
                ) AS revision_rank
            FROM holder_trade_signal_dates d
            JOIN holder_trade_db.holder_trade_events e
              ON e.ann_date <= d.signal_date
             AND DATE_DIFF(
                    'day',
                    STRPTIME(e.ann_date, '%Y%m%d'),
                    STRPTIME(d.signal_date, '%Y%m%d')
                 ) BETWEEN 0 AND {lookback_days}
            WHERE e.holder_type IN ('G', 'P')
        ),
        visible_events AS (
            SELECT * FROM visible_revisions WHERE revision_rank = 1
        )
        SELECT
            signal_date,
            ts_code AS symbol,
            MAX(ann_date) AS latest_event_ann_date,
            SUM(CASE WHEN in_de = 'IN' THEN change_ratio ELSE 0 END)
                AS gross_buy_ratio,
            SUM(CASE WHEN in_de = 'DE' THEN change_ratio ELSE 0 END)
                AS gross_sell_ratio,
            SUM(CASE WHEN in_de = 'IN' THEN change_ratio ELSE -change_ratio END)
                AS net_buy_ratio,
            COUNT(*) FILTER(WHERE in_de = 'IN') AS buy_event_count,
            COUNT(*) FILTER(WHERE in_de = 'DE') AS sell_event_count
        FROM visible_events
        GROUP BY signal_date, ts_code
        """
    )
    return HOLDER_TRADE_ASOF_TABLE


def load_holder_trade_snapshot(connection: DuckDBConnection) -> pd.DataFrame:
    """读取已经物化的重要股东净增持截面。"""
    return connection.execute(
        f"SELECT * FROM {HOLDER_TRADE_ASOF_TABLE} ORDER BY signal_date, symbol"
    ).fetchdf()


def _init_cache_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """初始化事件和同步游标表。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS holder_trade_events (
            event_key VARCHAR NOT NULL,
            ts_code VARCHAR NOT NULL,
            ann_date VARCHAR NOT NULL,
            holder_name VARCHAR NOT NULL,
            holder_type VARCHAR NOT NULL,
            in_de VARCHAR NOT NULL,
            change_vol DOUBLE,
            change_ratio DOUBLE NOT NULL,
            after_share DOUBLE,
            after_ratio DOUBLE,
            avg_price DOUBLE,
            total_share DOUBLE,
            begin_date VARCHAR,
            close_date VARCHAR,
            source VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(event_key, ann_date)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS holder_trade_sync_state (
            state_id INTEGER PRIMARY KEY,
            last_requested_end_date VARCHAR NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _upsert_events(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
) -> None:
    """按计划身份和公告日幂等写入事件修订。"""
    if frame.empty:
        return
    columns = [
        "event_key",
        "ts_code",
        "ann_date",
        "holder_name",
        "holder_type",
        "in_de",
        "change_vol",
        "change_ratio",
        "after_share",
        "after_ratio",
        "avg_price",
        "total_share",
        "begin_date",
        "close_date",
        "source",
    ]
    connection.register("_holder_trade_batch", frame[columns])
    try:
        assignments = ", ".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column not in {"event_key", "ann_date"}
        )
        connection.execute(
            f"""
            INSERT INTO holder_trade_events({", ".join(columns)})
            SELECT {", ".join(columns)} FROM _holder_trade_batch
            ON CONFLICT(event_key, ann_date) DO UPDATE SET
                {assignments},
                fetched_at=now()
            """
        )
    finally:
        connection.unregister("_holder_trade_batch")


def _event_key(row: pd.Series) -> str:
    """同一计划跨公告修订保持相同身份，缺开始日时退回公告日。"""
    start_anchor = (
        str(row["begin_date"])
        if pd.notna(row["begin_date"])
        else str(row["close_date"])
        if pd.notna(row["close_date"])
        else str(row["ann_date"])
    )
    payload = "|".join(
        [
            str(row["ts_code"]),
            str(row["holder_name"]),
            str(row["holder_type"]),
            str(row["in_de"]),
            start_anchor,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_requested_end(connection: duckdb.DuckDBPyConnection) -> date | None:
    row = connection.execute(
        """
        SELECT last_requested_end_date
        FROM holder_trade_sync_state
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
