"""北向个股持仓月末缓存与点时变化数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import duckdb
import numpy as np
import pandas as pd


HK_HOLD_CHANGE_TABLE = "hk_hold_change_asof"
HK_HOLD_COLUMNS = [
    "trade_date",
    "ts_code",
    "name",
    "vol",
    "ratio",
    "exchange",
]


class HkHoldClient(Protocol):
    """声明 Tushare 北向持仓接口。"""

    def hk_hold(self, trade_date: str) -> pd.DataFrame:
        """读取指定交易日的个股持仓快照。"""


class DuckDBConnection(Protocol):
    """声明点时门面所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


class TushareHkHoldClient:
    """真实 Tushare 北向持仓客户端。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def hk_hold(self, trade_date: str) -> pd.DataFrame:
        """只请求研究需要的稳定字段。"""
        return self._pro.hk_hold(
            trade_date=trade_date,
            fields=",".join(HK_HOLD_COLUMNS),
        )


@dataclass(frozen=True)
class HkHoldSyncResult:
    """一次月末缓存更新摘要。"""

    requested_dates: int
    skipped_dates: int
    api_calls: int
    fetched_rows: int
    stored_rows: int
    empty_dates: int


class HkHoldDuckDBStore:
    """幂等保存北向持仓快照和查询日志。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """创建缓存表，查询日志覆盖空结果日期。"""
        with duckdb.connect(str(self.path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS hk_hold_snapshots(
                    trade_date VARCHAR,
                    ts_code VARCHAR,
                    name VARCHAR,
                    vol DOUBLE,
                    ratio DOUBLE,
                    exchange VARCHAR,
                    PRIMARY KEY(trade_date, ts_code)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS hk_hold_sync_log(
                    trade_date VARCHAR PRIMARY KEY,
                    row_count BIGINT,
                    checked_at TIMESTAMP
                )
                """
            )

    def checked_dates(self) -> set[str]:
        """读取已经成功查询过的日期，包括空结果。"""
        with duckdb.connect(str(self.path), read_only=True) as connection:
            rows = connection.execute(
                "SELECT trade_date FROM hk_hold_sync_log"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def upsert_snapshot(
        self,
        trade_date: str,
        frame: pd.DataFrame,
    ) -> int:
        """原子写入单日快照并登记查询完成。"""
        normalized_date = _normalize_date(trade_date)
        cleaned = normalize_hk_hold_frame(frame, normalized_date)
        with duckdb.connect(str(self.path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                if not cleaned.empty:
                    connection.register("incoming_hk_hold", cleaned)
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO hk_hold_snapshots
                        SELECT trade_date, ts_code, name, vol, ratio, exchange
                        FROM incoming_hk_hold
                        """
                    )
                connection.execute(
                    """
                    INSERT INTO hk_hold_sync_log VALUES (?, ?, now())
                    ON CONFLICT(trade_date) DO UPDATE SET
                        row_count=excluded.row_count,
                        checked_at=excluded.checked_at
                    """,
                    [normalized_date, len(cleaned)],
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return int(len(cleaned))

    def count_rows(self) -> int:
        """返回当前快照总行数。"""
        with duckdb.connect(str(self.path), read_only=True) as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM hk_hold_snapshots"
                ).fetchone()[0]
            )


def update_hk_hold_month_ends(
    client: HkHoldClient,
    store: HkHoldDuckDBStore,
    trade_dates: list[str],
    *,
    force: bool = False,
) -> HkHoldSyncResult:
    """只更新尚未成功查询的月末日期。"""
    normalized = sorted({_normalize_date(value) for value in trade_dates})
    checked = set() if force else store.checked_dates()
    api_calls = 0
    skipped = 0
    fetched = 0
    empty_dates = 0
    for trade_date in normalized:
        if trade_date in checked:
            skipped += 1
            continue
        raw = client.hk_hold(trade_date)
        api_calls += 1
        fetched += len(raw)
        stored = store.upsert_snapshot(trade_date, raw)
        if stored == 0:
            empty_dates += 1
    return HkHoldSyncResult(
        requested_dates=len(normalized),
        skipped_dates=skipped,
        api_calls=api_calls,
        fetched_rows=fetched,
        stored_rows=store.count_rows(),
        empty_dates=empty_dates,
    )


def normalize_hk_hold_frame(
    frame: pd.DataFrame,
    requested_date: str,
) -> pd.DataFrame:
    """标准化持仓比例，过滤日期错配和非法数值。"""
    missing = [column for column in HK_HOLD_COLUMNS if column not in frame.columns]
    if missing:
        if frame.empty:
            return pd.DataFrame(columns=HK_HOLD_COLUMNS)
        raise ValueError(f"hk_hold frame missing columns: {missing}")
    if frame.empty:
        return pd.DataFrame(columns=HK_HOLD_COLUMNS)
    data = frame[HK_HOLD_COLUMNS].copy()
    data["trade_date"] = (
        data["trade_date"].fillna("").astype(str).str.replace("-", "")
    )
    data["ts_code"] = data["ts_code"].fillna("").astype(str)
    data["name"] = data["name"].fillna("").astype(str)
    data["exchange"] = data["exchange"].fillna("").astype(str)
    data["vol"] = pd.to_numeric(data["vol"], errors="coerce")
    data["ratio"] = pd.to_numeric(data["ratio"], errors="coerce")
    valid = (
        data["trade_date"].eq(requested_date)
        & data["ts_code"].str.len().gt(0)
        & data["ratio"].notna()
        & np.isfinite(data["ratio"])
        & data["ratio"].between(0.0, 100.0)
    )
    return (
        data[valid]
        .sort_values(["trade_date", "ts_code"])
        .drop_duplicates(["trade_date", "ts_code"], keep="last")
        .reset_index(drop=True)
    )


def attach_hk_hold_database(
    connection: DuckDBConnection,
    database_path: Path,
) -> None:
    """以只读方式挂载北向持仓缓存。"""
    if not database_path.exists():
        raise FileNotFoundError(f"缺少北向持仓缓存: {database_path.resolve()}")
    escaped = str(database_path.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS hk_hold_db (READ_ONLY)"
    )


def create_hk_hold_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """创建月末信号日表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE hk_hold_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO hk_hold_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_hk_hold_change_asof(
    connection: DuckDBConnection,
    *,
    min_gap_days: int = 20,
    max_gap_days: int = 45,
) -> str:
    """比较信号日前最近两个连续月末都可见的持仓比例。"""
    if not 0 < min_gap_days <= max_gap_days:
        raise ValueError("invalid month-end gap")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {HK_HOLD_CHANGE_TABLE} AS
        WITH available_periods AS (
            SELECT
                d.signal_date,
                p.trade_date,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date ORDER BY p.trade_date DESC
                ) AS period_rank
            FROM hk_hold_signal_dates d
            JOIN (
                SELECT DISTINCT trade_date
                FROM hk_hold_db.hk_hold_snapshots
            ) p ON p.trade_date <= d.signal_date
        ),
        selected_periods AS (
            SELECT *
            FROM available_periods
            WHERE period_rank <= 2
        ),
        current_hold AS (
            SELECT
                p.signal_date,
                p.trade_date AS current_trade_date,
                h.ts_code AS symbol,
                h.name,
                h.exchange,
                h.vol AS current_holding_volume,
                h.ratio AS current_holding_ratio
            FROM selected_periods p
            JOIN hk_hold_db.hk_hold_snapshots h
              ON p.trade_date = h.trade_date
            WHERE p.period_rank = 1
        ),
        prior_hold AS (
            SELECT
                p.signal_date,
                p.trade_date AS prior_trade_date,
                h.ts_code AS symbol,
                h.vol AS prior_holding_volume,
                h.ratio AS prior_holding_ratio
            FROM selected_periods p
            JOIN hk_hold_db.hk_hold_snapshots h
              ON p.trade_date = h.trade_date
            WHERE p.period_rank = 2
        )
        SELECT
            c.signal_date,
            c.symbol,
            c.name,
            c.exchange,
            c.current_trade_date,
            p.prior_trade_date,
            DATE_DIFF(
                'day',
                STRPTIME(p.prior_trade_date, '%Y%m%d'),
                STRPTIME(c.current_trade_date, '%Y%m%d')
            ) AS period_gap_days,
            c.current_holding_volume,
            p.prior_holding_volume,
            c.current_holding_ratio,
            p.prior_holding_ratio,
            c.current_holding_ratio - p.prior_holding_ratio
                AS holding_ratio_change
        FROM current_hold c
        JOIN prior_hold p
          ON c.signal_date = p.signal_date
         AND c.symbol = p.symbol
        WHERE DATE_DIFF(
                'day',
                STRPTIME(p.prior_trade_date, '%Y%m%d'),
                STRPTIME(c.current_trade_date, '%Y%m%d')
              ) BETWEEN {min_gap_days} AND {max_gap_days}
        """
    )
    return HK_HOLD_CHANGE_TABLE


def load_hk_hold_change_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取点时月度北向持仓变化。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {HK_HOLD_CHANGE_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    """校验并统一日期格式。"""
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid trade date: {value}")
    return normalized
