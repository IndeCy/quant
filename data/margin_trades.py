"""Tushare 融资融券明细的可断点增量缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable, Protocol

import duckdb
import pandas as pd


MARGIN_DETAIL_TABLE = "margin_detail"
MARGIN_SYNC_TABLE = "margin_sync_log"
NUMERIC_COLUMNS = [
    "rzye",
    "rqye",
    "rzmre",
    "rqyl",
    "rzche",
    "rqchl",
    "rqmcl",
    "rzrqye",
]


class MarginTradeClient(Protocol):
    """声明 Tushare 融资融券接口的最小能力。"""

    def margin_detail(self, **kwargs: Any) -> pd.DataFrame:
        """按交易日读取全部两融标的明细。"""


@dataclass(frozen=True)
class MarginTradeUpdateResult:
    """一次可恢复增量更新的结构化结果。"""

    requested_dates: int
    skipped_dates: int
    fetched_dates: int
    fetched_rows: int
    failed_dates: tuple[str, ...]

    @property
    def success(self) -> bool:
        """所有待更新交易日均成功才算完整。"""
        return not self.failed_dates


def update_margin_trade_cache(
    client: MarginTradeClient,
    database_path: Path,
    trade_dates: list[str],
    *,
    retry_times: int = 3,
    request_interval_seconds: float = 0.0,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> MarginTradeUpdateResult:
    """逐交易日更新，成功日期幂等跳过，失败日期下次继续。"""
    if retry_times <= 0:
        raise ValueError("retry_times must be positive")
    normalized_dates = sorted({_normalize_date(value) for value in trade_dates})
    database_path.parent.mkdir(parents=True, exist_ok=True)
    fetched_dates = 0
    fetched_rows = 0
    failed_dates: list[str] = []
    skipped_dates = 0
    with duckdb.connect(str(database_path)) as connection:
        _init_cache_schema(connection)
        completed = _load_completed_dates(connection)
        pending = [value for value in normalized_dates if value not in completed]
        skipped_dates = len(normalized_dates) - len(pending)
        total = len(pending)
        for index, trade_date in enumerate(pending, start=1):
            frame, error = _fetch_with_retry(
                client,
                trade_date,
                retry_times=retry_times,
            )
            if frame is None:
                failed_dates.append(trade_date)
                _record_sync(connection, trade_date, "FAILED", 0, error)
            else:
                normalized = normalize_margin_detail(frame, trade_date)
                if normalized.empty:
                    failed_dates.append(trade_date)
                    _record_sync(
                        connection,
                        trade_date,
                        "EMPTY",
                        0,
                        "交易日接口返回空数据",
                    )
                else:
                    _upsert_margin_detail(connection, normalized)
                    _record_sync(
                        connection,
                        trade_date,
                        "SUCCESS",
                        len(normalized),
                        "",
                    )
                    fetched_dates += 1
                    fetched_rows += len(normalized)
            if progress_callback is not None:
                progress_callback(index, total, trade_date)
            if request_interval_seconds > 0 and index < total:
                time.sleep(request_interval_seconds)
    return MarginTradeUpdateResult(
        requested_dates=len(normalized_dates),
        skipped_dates=skipped_dates,
        fetched_dates=fetched_dates,
        fetched_rows=fetched_rows,
        failed_dates=tuple(failed_dates),
    )


def normalize_margin_detail(
    frame: pd.DataFrame,
    requested_trade_date: str,
) -> pd.DataFrame:
    """清洗接口字段，并拒绝接口返回其他日期的数据。"""
    trade_date = _normalize_date(requested_trade_date)
    required = ["trade_date", "ts_code", *NUMERIC_COLUMNS]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"margin detail missing columns: {missing}")
    output_columns = [*required, "fetched_at", "source"]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)

    data = frame[required].copy()
    data["trade_date"] = data["trade_date"].astype(str).map(_normalize_date)
    data["ts_code"] = data["ts_code"].fillna("").astype(str).str.strip()
    for column in NUMERIC_COLUMNS:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data[
        data["trade_date"].eq(trade_date)
        & data["ts_code"].str.match(r"^\d{6}\.(SZ|SH|BJ)$")
    ].copy()
    data["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    data["source"] = "tushare_margin_detail"
    return (
        data[output_columns]
        .sort_values(["trade_date", "ts_code"])
        .drop_duplicates(["trade_date", "ts_code"], keep="last")
        .reset_index(drop=True)
    )


def attach_margin_trade_database(
    connection: Any,
    database_path: Path,
) -> None:
    """把研究缓存只读挂载到统一行情连接。"""
    if not database_path.exists():
        raise FileNotFoundError(f"缺少融资融券缓存: {database_path.resolve()}")
    escaped = str(database_path.resolve()).replace("'", "''")
    connection.execute(f"ATTACH DATABASE '{escaped}' AS margin_db (READ_ONLY)")


def _init_cache_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """初始化原始明细和逐日同步游标。"""
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MARGIN_DETAIL_TABLE}(
            trade_date VARCHAR NOT NULL,
            ts_code VARCHAR NOT NULL,
            rzye DOUBLE,
            rqye DOUBLE,
            rzmre DOUBLE,
            rqyl DOUBLE,
            rzche DOUBLE,
            rqchl DOUBLE,
            rqmcl DOUBLE,
            rzrqye DOUBLE,
            fetched_at VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            PRIMARY KEY(trade_date, ts_code)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MARGIN_SYNC_TABLE}(
            trade_date VARCHAR PRIMARY KEY,
            status VARCHAR NOT NULL,
            row_count BIGINT NOT NULL,
            error_message VARCHAR NOT NULL,
            updated_at VARCHAR NOT NULL
        )
        """
    )


def _load_completed_dates(connection: duckdb.DuckDBPyConnection) -> set[str]:
    rows = connection.execute(
        f"SELECT trade_date FROM {MARGIN_SYNC_TABLE} WHERE status = 'SUCCESS'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _fetch_with_retry(
    client: MarginTradeClient,
    trade_date: str,
    *,
    retry_times: int,
) -> tuple[pd.DataFrame | None, str]:
    """只对接口异常有限重试，最终错误交给同步日志。"""
    last_error = ""
    for attempt in range(retry_times):
        try:
            return client.margin_detail(trade_date=trade_date), ""
        except Exception as error:
            last_error = f"{type(error).__name__}: {error}"
            if attempt + 1 < retry_times:
                time.sleep(min(2 ** attempt, 4))
    return None, last_error


def _upsert_margin_detail(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
) -> None:
    connection.register("incoming_margin_detail", frame)
    try:
        columns = ["trade_date", "ts_code", *NUMERIC_COLUMNS, "fetched_at", "source"]
        names = ", ".join(columns)
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in [*NUMERIC_COLUMNS, "fetched_at", "source"]
        )
        connection.execute(
            f"""
            INSERT INTO {MARGIN_DETAIL_TABLE}({names})
            SELECT {names} FROM incoming_margin_detail
            ON CONFLICT(trade_date, ts_code) DO UPDATE SET {updates}
            """
        )
    finally:
        connection.unregister("incoming_margin_detail")


def _record_sync(
    connection: duckdb.DuckDBPyConnection,
    trade_date: str,
    status: str,
    row_count: int,
    error_message: str,
) -> None:
    connection.execute(
        f"""
        INSERT INTO {MARGIN_SYNC_TABLE}
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            status = excluded.status,
            row_count = excluded.row_count,
            error_message = excluded.error_message,
            updated_at = excluded.updated_at
        """,
        [
            trade_date,
            status,
            int(row_count),
            str(error_message),
            datetime.now().isoformat(timespec="seconds"),
        ],
    )


def _normalize_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid trade date: {value}")
    return normalized
