"""龙虎榜机构席位明细缓存与点时月度聚合门面。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Protocol

import duckdb
import numpy as np
import pandas as pd


TOP_INST_ASOF_TABLE = "top_inst_flow_asof"
TOP_INST_FIELDS = [
    "trade_date",
    "ts_code",
    "exalter",
    "side",
    "buy",
    "buy_rate",
    "sell",
    "sell_rate",
    "net_buy",
    "reason",
]


class TopInstClient(Protocol):
    """声明 Tushare 龙虎榜机构明细接口。"""

    def top_inst(self, trade_date: str) -> pd.DataFrame:
        """按单个交易日读取机构席位明细。"""


class TushareTopInstClient:
    """真实 Tushare 龙虎榜机构明细客户端。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def top_inst(self, trade_date: str) -> pd.DataFrame:
        """按官方接口约束逐交易日查询。"""
        return self._pro.top_inst(
            trade_date=trade_date,
            fields=",".join(TOP_INST_FIELDS),
        )


@dataclass(frozen=True)
class TopInstSyncResult:
    """一次可恢复同步的结构化结果。"""

    requested_dates: int
    skipped_dates: int
    fetched_dates: int
    fetched_rows: int
    normalized_rows: int
    stored_rows: int
    failed_dates: tuple[str, ...]

    @property
    def success(self) -> bool:
        """所有待更新日期成功，包括合法空结果。"""
        return not self.failed_dates


def update_top_inst_cache(
    client: TopInstClient,
    database_path: Path,
    trade_dates: list[str],
    *,
    retry_times: int = 3,
    request_interval_seconds: float = 0.0,
    source_row_limit: int = 10_000,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> TopInstSyncResult:
    """逐交易日更新，成功日期幂等跳过，失败后可从断点续跑。"""
    if retry_times <= 0 or source_row_limit <= 0:
        raise ValueError("retry_times and source_row_limit must be positive")
    dates = sorted({_normalize_date(value) for value in trade_dates})
    database_path.parent.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    fetched_dates = 0
    fetched_rows = 0
    normalized_rows = 0
    with duckdb.connect(str(database_path)) as connection:
        _init_schema(connection)
        completed = _load_completed_dates(connection)
        pending = [value for value in dates if value not in completed]
        for index, trade_date in enumerate(pending, start=1):
            raw, error = _fetch_with_retry(
                client,
                trade_date,
                retry_times=retry_times,
            )
            if raw is None:
                failed.append(trade_date)
                _record_sync(connection, trade_date, "FAILED", 0, 0, error)
            elif len(raw) >= source_row_limit:
                failed.append(trade_date)
                _record_sync(
                    connection,
                    trade_date,
                    "TRUNCATED",
                    len(raw),
                    0,
                    f"接口达到单次上限 {source_row_limit} 行",
                )
            else:
                normalized = normalize_top_inst_events(raw, trade_date)
                _replace_trade_date(connection, trade_date, normalized)
                _record_sync(
                    connection,
                    trade_date,
                    "SUCCESS",
                    len(raw),
                    len(normalized),
                    "",
                )
                fetched_dates += 1
                fetched_rows += len(raw)
                normalized_rows += len(normalized)
            if progress_callback is not None:
                progress_callback(index, len(pending), trade_date)
            if request_interval_seconds > 0 and index < len(pending):
                time.sleep(request_interval_seconds)
        stored_rows = int(
            connection.execute("SELECT COUNT(*) FROM top_inst_events").fetchone()[0]
        )
    return TopInstSyncResult(
        requested_dates=len(dates),
        skipped_dates=len(dates) - len(pending),
        fetched_dates=fetched_dates,
        fetched_rows=fetched_rows,
        normalized_rows=normalized_rows,
        stored_rows=stored_rows,
        failed_dates=tuple(failed),
    )


def normalize_top_inst_events(
    frame: pd.DataFrame,
    requested_trade_date: str,
) -> pd.DataFrame:
    """清洗明细，并消除买卖榜和多上榜理由造成的重复成交。"""
    trade_date = _normalize_date(requested_trade_date)
    output_columns = [
        "event_key",
        "trade_date",
        "ts_code",
        "exalter",
        "buy",
        "buy_rate",
        "sell",
        "sell_rate",
        "net_buy",
        "reason",
        "source_row_count",
        "side_count",
        "reason_count",
        "source",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    missing = [column for column in TOP_INST_FIELDS if column not in frame.columns]
    if missing:
        raise ValueError(f"top_inst frame missing columns: {missing}")

    data = frame[TOP_INST_FIELDS].copy()
    data["trade_date"] = (
        data["trade_date"].fillna("").astype(str).str.replace("-", "")
    )
    for column in ["ts_code", "exalter", "side", "reason"]:
        data[column] = data[column].fillna("").astype(str).str.strip()
    for column in ["buy", "buy_rate", "sell", "sell_rate", "net_buy"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = (
        data["trade_date"].eq(trade_date)
        & data["ts_code"].str.match(r"^\d{6}\.(SZ|SH|BJ)$")
        & data["exalter"].str.len().gt(0)
        & data["buy"].ge(0)
        & data["sell"].ge(0)
        & np.isfinite(data[["buy", "sell", "net_buy"]]).all(axis=1)
    )
    data = data[valid].copy()
    if data.empty:
        return pd.DataFrame(columns=output_columns)

    # side 和 reason 是榜单展示维度，不代表新增成交，不能重复计入净买入。
    natural = ["trade_date", "ts_code", "exalter", "buy", "sell", "net_buy"]
    grouped = data.groupby(natural, dropna=False, sort=False)
    counts = grouped.agg(
        source_row_count=("side", "size"),
        side_count=("side", "nunique"),
        reason_count=("reason", "nunique"),
    ).reset_index()
    chosen = (
        data.sort_values([*natural, "reason", "side"], kind="stable")
        .drop_duplicates(natural, keep="first")
        .merge(counts, on=natural, how="inner", validate="one_to_one")
    )
    chosen["event_key"] = chosen.apply(_event_key, axis=1)
    chosen["source"] = "tushare_top_inst"
    return chosen[output_columns].sort_values(
        ["trade_date", "ts_code", "event_key"]
    ).reset_index(drop=True)


def attach_top_inst_database(
    connection: Any,
    database_path: Path,
) -> None:
    """只读挂载机构席位缓存。"""
    if not database_path.exists():
        raise FileNotFoundError(f"缺少机构席位缓存: {database_path.resolve()}")
    escaped = str(database_path.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS top_inst_db (READ_ONLY)"
    )


def create_top_inst_signal_dates(
    connection: Any,
    signal_dates: list[str],
) -> None:
    """创建月末信号日表。"""
    dates = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE top_inst_signal_dates("
        "signal_date VARCHAR)"
    )
    if dates:
        connection.executemany(
            "INSERT INTO top_inst_signal_dates VALUES (?)",
            [(value,) for value in dates],
        )


def materialize_top_inst_flow_asof(
    connection: Any,
    *,
    lookback_trading_days: int = 20,
) -> str:
    """按真实交易日聚合信号日及此前可见的机构席位净买入。"""
    if lookback_trading_days <= 0:
        raise ValueError("lookback_trading_days must be positive")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {TOP_INST_ASOF_TABLE} AS
        WITH calendar AS (
            SELECT
                trade_date,
                ROW_NUMBER() OVER(ORDER BY trade_date) AS trade_ordinal
            FROM (SELECT DISTINCT trade_date FROM features)
        ),
        signals AS (
            SELECT d.signal_date, c.trade_ordinal AS signal_ordinal
            FROM top_inst_signal_dates d
            JOIN calendar c ON d.signal_date = c.trade_date
        ),
        visible_events AS (
            SELECT
                s.signal_date,
                e.event_key,
                e.trade_date,
                e.ts_code AS symbol,
                e.exalter,
                e.buy,
                e.sell,
                e.net_buy,
                e.source_row_count
            FROM signals s
            JOIN calendar c
              ON c.trade_ordinal BETWEEN
                 s.signal_ordinal - {lookback_trading_days - 1}
                 AND s.signal_ordinal
            JOIN top_inst_db.top_inst_events e
              ON e.trade_date = c.trade_date
        )
        SELECT
            signal_date,
            symbol,
            MAX(trade_date) AS latest_event_date,
            COUNT(*) AS unique_seat_events,
            COUNT(DISTINCT trade_date) AS event_days,
            SUM(source_row_count) AS source_rows,
            SUM(buy) AS total_buy,
            SUM(sell) AS total_sell,
            SUM(net_buy) AS total_net_buy
        FROM visible_events
        GROUP BY signal_date, symbol
        """
    )
    return TOP_INST_ASOF_TABLE


def load_top_inst_flow_snapshot(connection: Any) -> pd.DataFrame:
    """读取机构席位月末聚合结果。"""
    return connection.execute(
        f"SELECT * FROM {TOP_INST_ASOF_TABLE} ORDER BY signal_date, symbol"
    ).fetchdf()


def _init_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """初始化事件表与逐日同步日志。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS top_inst_events(
            event_key VARCHAR PRIMARY KEY,
            trade_date VARCHAR NOT NULL,
            ts_code VARCHAR NOT NULL,
            exalter VARCHAR NOT NULL,
            buy DOUBLE NOT NULL,
            buy_rate DOUBLE,
            sell DOUBLE NOT NULL,
            sell_rate DOUBLE,
            net_buy DOUBLE NOT NULL,
            reason VARCHAR NOT NULL,
            source_row_count INTEGER NOT NULL,
            side_count INTEGER NOT NULL,
            reason_count INTEGER NOT NULL,
            source VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS top_inst_sync_log(
            trade_date VARCHAR PRIMARY KEY,
            status VARCHAR NOT NULL,
            raw_row_count BIGINT NOT NULL,
            normalized_row_count BIGINT NOT NULL,
            error_message VARCHAR NOT NULL,
            updated_at VARCHAR NOT NULL
        )
        """
    )


def _replace_trade_date(
    connection: duckdb.DuckDBPyConnection,
    trade_date: str,
    frame: pd.DataFrame,
) -> None:
    """事务替换单日完整结果，空结果也会清理旧缓存。"""
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            "DELETE FROM top_inst_events WHERE trade_date = ?",
            [trade_date],
        )
        if not frame.empty:
            columns = [
                "event_key",
                "trade_date",
                "ts_code",
                "exalter",
                "buy",
                "buy_rate",
                "sell",
                "sell_rate",
                "net_buy",
                "reason",
                "source_row_count",
                "side_count",
                "reason_count",
                "source",
            ]
            connection.register("_top_inst_batch", frame[columns])
            try:
                names = ", ".join(columns)
                connection.execute(
                    f"""
                    INSERT INTO top_inst_events({names})
                    SELECT {names} FROM _top_inst_batch
                    """
                )
            finally:
                connection.unregister("_top_inst_batch")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _load_completed_dates(
    connection: duckdb.DuckDBPyConnection,
) -> set[str]:
    rows = connection.execute(
        "SELECT trade_date FROM top_inst_sync_log WHERE status = 'SUCCESS'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _fetch_with_retry(
    client: TopInstClient,
    trade_date: str,
    *,
    retry_times: int,
) -> tuple[pd.DataFrame | None, str]:
    """有限重试接口异常，失败日期留给下次续跑。"""
    last_error = ""
    for attempt in range(retry_times):
        try:
            return client.top_inst(trade_date), ""
        except Exception as error:
            last_error = f"{type(error).__name__}: {error}"
            if attempt + 1 < retry_times:
                time.sleep(min(2 ** attempt, 4))
    return None, last_error


def _record_sync(
    connection: duckdb.DuckDBPyConnection,
    trade_date: str,
    status: str,
    raw_rows: int,
    normalized_rows: int,
    error_message: str,
) -> None:
    connection.execute(
        """
        INSERT INTO top_inst_sync_log VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            status=excluded.status,
            raw_row_count=excluded.raw_row_count,
            normalized_row_count=excluded.normalized_row_count,
            error_message=excluded.error_message,
            updated_at=excluded.updated_at
        """,
        [
            trade_date,
            status,
            int(raw_rows),
            int(normalized_rows),
            str(error_message),
            datetime.now().isoformat(timespec="seconds"),
        ],
    )


def _event_key(row: pd.Series) -> str:
    """对真实成交身份生成稳定键，排除榜单展示维度。"""
    payload = [
        str(row["trade_date"]),
        str(row["ts_code"]),
        str(row["exalter"]),
        float(row["buy"]),
        float(row["sell"]),
        float(row["net_buy"]),
    ]
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid trade date: {value}")
    return normalized
