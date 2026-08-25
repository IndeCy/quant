"""Tushare个股订单规模资金流缓存与点时聚合门面。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable, Protocol

import duckdb
import numpy as np
import pandas as pd


ORDER_FLOW_ASOF_TABLE = "large_order_flow_asof"
AMOUNT_COLUMNS = [
    "buy_sm_amount",
    "sell_sm_amount",
    "buy_md_amount",
    "sell_md_amount",
    "buy_lg_amount",
    "sell_lg_amount",
    "buy_elg_amount",
    "sell_elg_amount",
]
MONEYFLOW_FIELDS = ["trade_date", "ts_code", *AMOUNT_COLUMNS, "net_mf_amount"]


class OrderFlowClient(Protocol):
    """声明Tushare个股资金流接口。"""

    def moneyflow(self, trade_date: str) -> pd.DataFrame:
        """按交易日读取全市场订单规模分类。"""


class TushareOrderFlowClient:
    """真实Tushare订单规模资金流客户端。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def moneyflow(self, trade_date: str) -> pd.DataFrame:
        """只请求可复现因子和恒等式审计所需字段。"""
        return self._pro.moneyflow(
            trade_date=trade_date,
            fields=",".join(MONEYFLOW_FIELDS),
        )


@dataclass(frozen=True)
class OrderFlowSyncResult:
    """一次可恢复逐日同步摘要。"""

    requested_dates: int
    skipped_dates: int
    fetched_dates: int
    fetched_rows: int
    stored_rows: int
    failed_dates: tuple[str, ...]

    @property
    def success(self) -> bool:
        """所有交易日成功，包括合法空结果。"""
        return not self.failed_dates


def update_order_flow_cache(
    client: OrderFlowClient,
    database_path: Path,
    trade_dates: list[str],
    *,
    retry_times: int = 3,
    request_interval_seconds: float = 0.0,
    source_row_limit: int = 6_000,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> OrderFlowSyncResult:
    """逐交易日同步，成功日期跳过，失败日期下次断点续跑。"""
    if retry_times <= 0 or source_row_limit <= 0:
        raise ValueError("retry_times and source_row_limit must be positive")
    dates = sorted({_normalize_date(value) for value in trade_dates})
    database_path.parent.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    fetched_dates = 0
    fetched_rows = 0
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
                normalized = normalize_order_flow(raw, trade_date)
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
            if progress_callback is not None:
                progress_callback(index, len(pending), trade_date)
            if request_interval_seconds > 0 and index < len(pending):
                time.sleep(request_interval_seconds)
        stored_rows = int(
            connection.execute("SELECT COUNT(*) FROM order_flow_daily").fetchone()[0]
        )
    return OrderFlowSyncResult(
        requested_dates=len(dates),
        skipped_dates=len(dates) - len(pending),
        fetched_dates=fetched_dates,
        fetched_rows=fetched_rows,
        stored_rows=stored_rows,
        failed_dates=tuple(failed),
    )


def normalize_order_flow(
    frame: pd.DataFrame,
    requested_trade_date: str,
) -> pd.DataFrame:
    """清洗原始分类金额并压缩为四个可审计事实字段。"""
    trade_date = _normalize_date(requested_trade_date)
    output_columns = [
        "trade_date",
        "ts_code",
        "large_net_amount_wan",
        "all_net_amount_wan",
        "classified_amount_wan",
        "source_net_amount_wan",
        "source",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    missing = [column for column in MONEYFLOW_FIELDS if column not in frame.columns]
    if missing:
        raise ValueError(f"moneyflow frame missing columns: {missing}")
    data = frame[MONEYFLOW_FIELDS].copy()
    data["trade_date"] = (
        data["trade_date"].fillna("").astype(str).str.replace("-", "")
    )
    data["ts_code"] = data["ts_code"].fillna("").astype(str).str.strip()
    for column in [*AMOUNT_COLUMNS, "net_mf_amount"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = (
        data["trade_date"].eq(trade_date)
        & data["ts_code"].str.match(r"^\d{6}\.(SZ|SH|BJ)$")
        & np.isfinite(data[[*AMOUNT_COLUMNS, "net_mf_amount"]]).all(axis=1)
        & data[AMOUNT_COLUMNS].ge(0).all(axis=1)
    )
    data = data[valid].copy()
    if data.empty:
        return pd.DataFrame(columns=output_columns)

    data["large_net_amount_wan"] = (
        data["buy_lg_amount"]
        + data["buy_elg_amount"]
        - data["sell_lg_amount"]
        - data["sell_elg_amount"]
    )
    buys = ["buy_sm_amount", "buy_md_amount", "buy_lg_amount", "buy_elg_amount"]
    sells = [
        "sell_sm_amount",
        "sell_md_amount",
        "sell_lg_amount",
        "sell_elg_amount",
    ]
    data["all_net_amount_wan"] = data[buys].sum(axis=1) - data[sells].sum(
        axis=1
    )
    data["classified_amount_wan"] = data[AMOUNT_COLUMNS].sum(axis=1)
    data["source_net_amount_wan"] = data["net_mf_amount"]
    data["source"] = "tushare_moneyflow"
    return (
        data[output_columns]
        .sort_values(["trade_date", "ts_code"])
        .drop_duplicates(["trade_date", "ts_code"], keep="last")
        .reset_index(drop=True)
    )


def attach_order_flow_database(
    connection: Any,
    database_path: Path,
) -> None:
    """只读挂载订单流缓存。"""
    if not database_path.exists():
        raise FileNotFoundError(f"缺少订单流缓存: {database_path.resolve()}")
    escaped = str(database_path.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS order_flow_db (READ_ONLY)"
    )


def create_order_flow_signal_dates(
    connection: Any,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表。"""
    dates = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE order_flow_signal_dates("
        "signal_date VARCHAR)"
    )
    if dates:
        connection.executemany(
            "INSERT INTO order_flow_signal_dates VALUES (?)",
            [(value,) for value in dates],
        )


def materialize_large_order_flow_asof(
    connection: Any,
    *,
    lookback_trading_days: int = 20,
) -> str:
    """按真实交易日聚合信号日前的大单和特大单净流入占比。"""
    if lookback_trading_days <= 0:
        raise ValueError("lookback_trading_days must be positive")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {ORDER_FLOW_ASOF_TABLE} AS
        WITH calendar AS (
            SELECT
                trade_date,
                ROW_NUMBER() OVER(ORDER BY trade_date) AS trade_ordinal
            FROM (SELECT DISTINCT trade_date FROM features)
        ),
        signals AS (
            SELECT d.signal_date, c.trade_ordinal AS signal_ordinal
            FROM order_flow_signal_dates d
            JOIN calendar c ON d.signal_date = c.trade_date
        ),
        visible AS (
            SELECT
                s.signal_date,
                o.trade_date,
                o.ts_code AS symbol,
                o.large_net_amount_wan,
                o.all_net_amount_wan,
                o.classified_amount_wan,
                o.source_net_amount_wan
            FROM signals s
            JOIN calendar c
              ON c.trade_ordinal BETWEEN
                 s.signal_ordinal - {lookback_trading_days - 1}
                 AND s.signal_ordinal
            JOIN order_flow_db.order_flow_daily o
              ON o.trade_date = c.trade_date
        )
        SELECT
            signal_date,
            symbol,
            MAX(trade_date) AS latest_flow_date,
            COUNT(*) AS observations,
            SUM(large_net_amount_wan) AS large_net_amount_wan,
            SUM(all_net_amount_wan) AS all_net_amount_wan,
            SUM(source_net_amount_wan) AS source_net_amount_wan,
            SUM(classified_amount_wan) AS classified_amount_wan,
            SUM(large_net_amount_wan)
                / NULLIF(SUM(classified_amount_wan), 0)
                AS large_order_net_share,
            SUM(source_net_amount_wan)
                / NULLIF(SUM(classified_amount_wan), 0)
                AS total_net_share,
            2.0 * SUM(source_net_amount_wan)
                / NULLIF(SUM(classified_amount_wan), 0)
                AS source_net_turnover_share
        FROM visible
        GROUP BY signal_date, symbol
        """
    )
    return ORDER_FLOW_ASOF_TABLE


def load_large_order_flow_snapshot(connection: Any) -> pd.DataFrame:
    """读取月末订单流聚合截面。"""
    return connection.execute(
        f"SELECT * FROM {ORDER_FLOW_ASOF_TABLE} ORDER BY signal_date, symbol"
    ).fetchdf()


def _init_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """初始化紧凑日表和逐日同步日志。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS order_flow_daily(
            trade_date VARCHAR NOT NULL,
            ts_code VARCHAR NOT NULL,
            large_net_amount_wan DOUBLE NOT NULL,
            all_net_amount_wan DOUBLE NOT NULL,
            classified_amount_wan DOUBLE NOT NULL,
            source_net_amount_wan DOUBLE NOT NULL,
            source VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(trade_date, ts_code)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS order_flow_sync_log(
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
    """事务替换单日完整结果。"""
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            "DELETE FROM order_flow_daily WHERE trade_date = ?",
            [trade_date],
        )
        if not frame.empty:
            columns = [
                "trade_date",
                "ts_code",
                "large_net_amount_wan",
                "all_net_amount_wan",
                "classified_amount_wan",
                "source_net_amount_wan",
                "source",
            ]
            connection.register("_order_flow_batch", frame[columns])
            try:
                names = ", ".join(columns)
                connection.execute(
                    f"""
                    INSERT INTO order_flow_daily({names})
                    SELECT {names} FROM _order_flow_batch
                    """
                )
            finally:
                connection.unregister("_order_flow_batch")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _load_completed_dates(
    connection: duckdb.DuckDBPyConnection,
) -> set[str]:
    rows = connection.execute(
        "SELECT trade_date FROM order_flow_sync_log WHERE status='SUCCESS'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _fetch_with_retry(
    client: OrderFlowClient,
    trade_date: str,
    *,
    retry_times: int,
) -> tuple[pd.DataFrame | None, str]:
    """有限重试接口异常。"""
    last_error = ""
    for attempt in range(retry_times):
        try:
            return client.moneyflow(trade_date), ""
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
        INSERT INTO order_flow_sync_log VALUES (?, ?, ?, ?, ?, ?)
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


def _normalize_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid trade date: {value}")
    return normalized
