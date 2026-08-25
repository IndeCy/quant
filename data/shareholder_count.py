"""股东户数增量缓存与公告日 as-of 数据门面。"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import duckdb
import numpy as np
import pandas as pd


SHAREHOLDER_ASOF_TABLE = "shareholder_concentration_asof"


class ShareholderCountClient(Protocol):
    """声明 Tushare 股东户数接口能力。"""

    def stk_holdernumber(self, **kwargs: Any) -> pd.DataFrame:
        """按公告日期查询股东户数。"""


class DuckDBConnection(Protocol):
    """声明 as-of 门面所需的最小 DuckDB 能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class ShareholderSyncResult:
    """一次增量同步结果。"""

    requested_start: str
    requested_end: str
    fetched_rows: int
    stored_rows: int
    api_calls: int


def update_shareholder_count_cache(
    client: ShareholderCountClient,
    database_path: Path,
    *,
    start_date: str,
    end_date: str,
    force_full: bool = False,
    overlap_days: int = 31,
    page_size: int = 3000,
) -> ShareholderSyncResult:
    """按公告月分页更新缓存，重复事件使用确定性主键覆盖。"""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    if overlap_days < 0 or page_size <= 0:
        raise ValueError("overlap_days and page_size must be non-negative")

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
                raw = client.stk_holdernumber(
                    start_date=month_start.strftime("%Y%m%d"),
                    end_date=month_end.strftime("%Y%m%d"),
                    limit=page_size,
                    offset=offset,
                )
                api_calls += 1
                normalized = normalize_shareholder_events(raw)
                fetched_rows += len(normalized)
                _upsert_events(connection, normalized)
                if len(raw) < page_size:
                    break
                offset += len(raw)

        connection.execute(
            """
            INSERT INTO shareholder_sync_state(
                state_id, last_requested_end_date, updated_at
            ) VALUES (1, ?, now())
            ON CONFLICT(state_id) DO UPDATE SET
                last_requested_end_date=excluded.last_requested_end_date,
                updated_at=now()
            """,
            [end.strftime("%Y%m%d")],
        )
        stored_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM shareholder_count_events"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return ShareholderSyncResult(
        requested_start=effective_start.strftime("%Y%m%d"),
        requested_end=end.strftime("%Y%m%d"),
        fetched_rows=fetched_rows,
        stored_rows=stored_rows,
        api_calls=api_calls,
    )


def normalize_shareholder_events(frame: pd.DataFrame) -> pd.DataFrame:
    """统一日期和数值，丢弃空户数及无法识别的事件。"""
    required = ["ts_code", "ann_date", "end_date", "holder_num"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"shareholder events missing columns: {missing}")
    if frame.empty:
        return pd.DataFrame(columns=[*required, "source"])

    data = frame[required].copy()
    ann_date = pd.to_datetime(
        data["ann_date"],
        errors="coerce",
        format="mixed",
    )
    end_date = pd.to_datetime(
        data["end_date"],
        errors="coerce",
        format="mixed",
    )
    data["holder_num"] = pd.to_numeric(data["holder_num"], errors="coerce")
    valid = (
        data["ts_code"].fillna("").astype(str).str.len().gt(0)
        & ann_date.notna()
        & end_date.notna()
        & data["holder_num"].gt(0)
        & np.isfinite(data["holder_num"])
        & end_date.le(ann_date)
    )
    data = data[valid].copy()
    data["ann_date"] = ann_date[valid].dt.strftime("%Y%m%d")
    data["end_date"] = end_date[valid].dt.strftime("%Y%m%d")
    data["ts_code"] = data["ts_code"].astype(str)
    data["holder_num"] = data["holder_num"].round().astype("int64")
    data["source"] = "tushare_stk_holdernumber"
    return (
        data.sort_values(["ts_code", "ann_date", "end_date"])
        .drop_duplicates(["ts_code", "ann_date", "end_date"], keep="last")
        .reset_index(drop=True)
    )


def attach_shareholder_count_database(
    connection: DuckDBConnection,
    database_path: Path,
) -> None:
    """只读挂载已缓存的股东户数数据库。"""
    if not database_path.exists():
        raise FileNotFoundError(f"缺少股东户数缓存: {database_path.resolve()}")
    escaped = str(database_path.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS shareholder_db (READ_ONLY)"
    )


def create_shareholder_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日临时表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE shareholder_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO shareholder_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_shareholder_concentration_asof(
    connection: DuckDBConnection,
    *,
    min_gap_days: int = 20,
    max_gap_days: int = 180,
    max_staleness_days: int = 180,
) -> str:
    """用信号日前最近两个有效披露期计算标准化筹码集中速度。"""
    if not 0 < min_gap_days <= max_gap_days:
        raise ValueError("invalid holder period gap")
    if max_staleness_days <= 0:
        raise ValueError("max_staleness_days must be positive")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {SHAREHOLDER_ASOF_TABLE} AS
        WITH visible_revisions AS (
            SELECT
                d.signal_date,
                e.ts_code AS symbol,
                e.ann_date,
                e.end_date,
                CAST(e.holder_num AS DOUBLE) AS holder_num,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, e.ts_code, e.end_date
                    ORDER BY e.ann_date DESC
                ) AS revision_rank
            FROM shareholder_signal_dates d
            JOIN shareholder_db.shareholder_count_events e
              ON e.ann_date <= d.signal_date
             AND e.end_date <= d.signal_date
        ),
        latest_revisions AS (
            SELECT * FROM visible_revisions WHERE revision_rank = 1
        ),
        ranked_periods AS (
            SELECT
                *,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY end_date DESC, ann_date DESC
                ) AS period_rank
            FROM latest_revisions
        ),
        pairs AS (
            SELECT
                signal_date,
                symbol,
                MAX(ann_date) FILTER(WHERE period_rank = 1) AS latest_ann_date,
                MAX(end_date) FILTER(WHERE period_rank = 1) AS latest_end_date,
                MAX(holder_num) FILTER(WHERE period_rank = 1) AS latest_holder_num,
                MAX(end_date) FILTER(WHERE period_rank = 2) AS prior_end_date,
                MAX(holder_num) FILTER(WHERE period_rank = 2) AS prior_holder_num
            FROM ranked_periods
            WHERE period_rank <= 2
            GROUP BY signal_date, symbol
        ),
        measured AS (
            SELECT
                *,
                DATE_DIFF(
                    'day',
                    STRPTIME(prior_end_date, '%Y%m%d'),
                    STRPTIME(latest_end_date, '%Y%m%d')
                ) AS period_gap_days,
                DATE_DIFF(
                    'day',
                    STRPTIME(latest_end_date, '%Y%m%d'),
                    STRPTIME(signal_date, '%Y%m%d')
                ) AS staleness_days,
                -LN(latest_holder_num / prior_holder_num) * 90.0
                    / NULLIF(
                        DATE_DIFF(
                            'day',
                            STRPTIME(prior_end_date, '%Y%m%d'),
                            STRPTIME(latest_end_date, '%Y%m%d')
                        ),
                        0
                    ) AS concentration_rate_90d
            FROM pairs
            WHERE latest_holder_num > 0 AND prior_holder_num > 0
        )
        SELECT
            signal_date,
            symbol,
            latest_ann_date,
            latest_end_date,
            latest_holder_num,
            prior_end_date,
            prior_holder_num,
            period_gap_days,
            staleness_days,
            concentration_rate_90d
        FROM measured
        WHERE period_gap_days BETWEEN {min_gap_days} AND {max_gap_days}
          AND staleness_days BETWEEN 0 AND {max_staleness_days}
        """
    )
    return SHAREHOLDER_ASOF_TABLE


def load_shareholder_concentration_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经物化的筹码集中点时截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {SHAREHOLDER_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _init_cache_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """初始化可增量覆盖的事件表和同步游标。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shareholder_count_events (
            ts_code VARCHAR NOT NULL,
            ann_date VARCHAR NOT NULL,
            end_date VARCHAR NOT NULL,
            holder_num BIGINT NOT NULL,
            source VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(ts_code, ann_date, end_date)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shareholder_sync_state (
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
    """按事件主键幂等覆盖清洗后的记录。"""
    if frame.empty:
        return
    batch = frame[
        ["ts_code", "ann_date", "end_date", "holder_num", "source"]
    ].copy()
    connection.register("_shareholder_event_batch", batch)
    try:
        connection.execute(
            """
            INSERT INTO shareholder_count_events(
                ts_code, ann_date, end_date, holder_num, source
            )
            SELECT ts_code, ann_date, end_date, holder_num, source
            FROM _shareholder_event_batch
            ON CONFLICT(ts_code, ann_date, end_date) DO UPDATE SET
                holder_num=excluded.holder_num,
                source=excluded.source,
                fetched_at=now()
            """
        )
    finally:
        connection.unregister("_shareholder_event_batch")


def _last_requested_end(connection: duckdb.DuckDBPyConnection) -> date | None:
    row = connection.execute(
        """
        SELECT last_requested_end_date
        FROM shareholder_sync_state
        WHERE state_id = 1
        """
    ).fetchone()
    return _parse_date(row[0]) if row else None


def _month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """把请求拆成自然月，避免单次接口达到行数上限。"""
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
    normalized = _normalize_date(value)
    return datetime.strptime(normalized, "%Y%m%d").date()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
