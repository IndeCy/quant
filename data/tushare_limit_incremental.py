"""Tushare 涨跌停列表增量缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import duckdb
import pandas as pd

from runtime.config import get_config_value


LIMIT_LIST_COLUMNS = [
    "trade_date",
    "ts_code",
    "name",
    "close",
    "pct_chg",
    "limit",
    "amount",
    "fd_amount",
    "first_time",
    "last_time",
    "open_times",
]
STANDARD_COLUMNS = [
    "trade_date",
    "ts_code",
    "name",
    "close",
    "pct_chg",
    "limit_type",
    "amount",
    "fd_amount",
    "first_time",
    "last_time",
    "open_times",
]


class LimitListClient(Protocol):
    """涨跌停列表客户端协议，便于测试替换真实 Tushare。"""

    def limit_list_d(self, trade_date: str) -> pd.DataFrame: ...


class TushareLimitClient:
    """Tushare 涨跌停列表客户端，token 统一来自本地配置。"""

    def __init__(self, token: str | None = None) -> None:
        resolved = token if token is not None else get_config_value("TUSHARE_TOKEN")
        if not resolved:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(resolved)

    def limit_list_d(self, trade_date: str) -> pd.DataFrame:
        """读取单个交易日涨跌停列表。"""
        return self._pro.limit_list_d(trade_date=trade_date, fields=",".join(LIMIT_LIST_COLUMNS))


@dataclass(frozen=True)
class LimitListDuckDBStore:
    """本地 DuckDB 涨跌停缓存。"""

    path: Path

    def ensure_schema(self) -> None:
        """创建涨跌停缓存表，主键保证同日重复更新幂等。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self.path)) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS limit_list_daily (
                  trade_date VARCHAR,
                  ts_code VARCHAR,
                  name VARCHAR,
                  close DOUBLE,
                  pct_chg DOUBLE,
                  limit_type VARCHAR,
                  amount DOUBLE,
                  fd_amount DOUBLE,
                  first_time VARCHAR,
                  last_time VARCHAR,
                  open_times INTEGER,
                  PRIMARY KEY (trade_date, ts_code)
                )
                """
            )

    def upsert(self, frame: pd.DataFrame) -> int:
        """标准化并写入涨跌停数据。"""
        self.ensure_schema()
        cleaned = _normalize_limit_frame(frame)
        if cleaned.empty:
            return 0
        with duckdb.connect(str(self.path)) as con:
            con.register("incoming_limit_list", cleaned)
            con.execute("INSERT OR REPLACE INTO limit_list_daily SELECT * FROM incoming_limit_list")
        return int(len(cleaned))

    def load(self, start_date: str, end_date: str) -> pd.DataFrame:
        """读取指定区间的标准涨跌停缓存。"""
        self.ensure_schema()
        with duckdb.connect(str(self.path), read_only=True) as con:
            return con.execute(
                """
                SELECT * FROM limit_list_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date, ts_code
                """,
                [start_date, end_date],
            ).df()


def update_limit_list_range(
    store: LimitListDuckDBStore,
    client: LimitListClient,
    trade_dates: list[str],
) -> dict[str, object]:
    """按交易日更新涨跌停缓存。"""
    rows_written = 0
    updated_dates: list[str] = []
    for trade_date in trade_dates:
        rows_written += store.upsert(client.limit_list_d(trade_date))
        updated_dates.append(trade_date)
    return {"updated_dates": updated_dates, "rows_written": rows_written}


def _normalize_limit_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """把 Tushare 原始字段归一成系统字段。"""
    if frame.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    renamed = frame.rename(columns={"limit": "limit_type"}).copy()
    for column in ["trade_date", "ts_code", "name", "limit_type", "first_time", "last_time"]:
        if column not in renamed.columns:
            renamed[column] = ""
        renamed[column] = renamed[column].fillna("").astype(str)
    for column in ["close", "pct_chg", "amount", "fd_amount"]:
        if column not in renamed.columns:
            renamed[column] = 0.0
        renamed[column] = pd.to_numeric(renamed[column], errors="coerce").fillna(0.0)
    if "open_times" not in renamed.columns:
        renamed["open_times"] = 0
    renamed["open_times"] = pd.to_numeric(renamed["open_times"], errors="coerce").fillna(0).astype(int)
    return renamed[STANDARD_COLUMNS]
