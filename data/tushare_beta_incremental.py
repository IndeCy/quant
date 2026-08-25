"""Tushare beta 观测数据增量缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import duckdb
import pandas as pd

from runtime.config import get_config_value


DAILY_BASIC_COLUMNS = ["trade_date", "ts_code", "pe_ttm", "pb", "dv_ttm", "total_mv", "circ_mv", "turnover_rate"]
INDEX_DAILYBASIC_COLUMNS = ["trade_date", "ts_code", "pe_ttm", "pb", "turnover_rate", "total_mv"]
FUND_SHARE_COLUMNS = ["trade_date", "ts_code", "fd_share"]
MONEYFLOW_HSGT_COLUMNS = ["trade_date", "north_money", "south_money", "hgt", "sgt"]
MARGIN_COLUMNS = ["trade_date", "exchange_id", "rzye", "rzmre", "rqye", "rzrqye"]
MARGIN_DETAIL_COLUMNS = ["trade_date", "ts_code", "rzye", "rqye", "rzmre", "rqmcl", "rzrqye"]


class TushareBetaClient(Protocol):
    """Beta P0 数据客户端协议，便于单测注入。"""

    def daily_basic(self, trade_date: str) -> pd.DataFrame: ...

    def index_dailybasic(self, trade_date: str) -> pd.DataFrame: ...

    def fund_share(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    def moneyflow_hsgt(self, start_date: str, end_date: str) -> pd.DataFrame: ...

    def margin(self, trade_date: str) -> pd.DataFrame: ...

    def margin_detail(self, trade_date: str) -> pd.DataFrame: ...


class TushareBetaProClient:
    """真实 Tushare beta 数据客户端，token 统一来自本地配置。"""

    def __init__(self, token: str | None = None) -> None:
        resolved = token if token is not None else get_config_value("TUSHARE_TOKEN")
        if not resolved:
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(resolved)

    def daily_basic(self, trade_date: str) -> pd.DataFrame:
        """读取全市场估值、市值、股息率基础数据。"""
        return self._pro.daily_basic(trade_date=trade_date, fields=",".join(DAILY_BASIC_COLUMNS))

    def index_dailybasic(self, trade_date: str) -> pd.DataFrame:
        """读取指数估值和成交基础数据。"""
        return self._pro.index_dailybasic(trade_date=trade_date, fields=",".join(INDEX_DAILYBASIC_COLUMNS))

    def fund_share(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """读取 ETF 份额变化。"""
        return self._pro.fund_share(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=",".join(FUND_SHARE_COLUMNS))

    def moneyflow_hsgt(self, start_date: str, end_date: str) -> pd.DataFrame:
        """读取沪深港通资金汇总。"""
        return self._pro.moneyflow_hsgt(start_date=start_date, end_date=end_date, fields=",".join(MONEYFLOW_HSGT_COLUMNS))

    def margin(self, trade_date: str) -> pd.DataFrame:
        """读取两融市场汇总。"""
        return self._pro.margin(trade_date=trade_date, fields=",".join(MARGIN_COLUMNS))

    def margin_detail(self, trade_date: str) -> pd.DataFrame:
        """读取个股两融明细。"""
        return self._pro.margin_detail(trade_date=trade_date, fields=",".join(MARGIN_DETAIL_COLUMNS))


@dataclass(frozen=True)
class BetaUpdateResult:
    """单日 beta P0 数据更新摘要。"""

    trade_date: str
    daily_basic_rows: int
    index_dailybasic_rows: int
    fund_share_rows: int
    moneyflow_hsgt_rows: int
    margin_rows: int
    margin_detail_rows: int


class BetaIncrementalStore:
    """保存 beta 观测扩展数据，不改写行情和策略库。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))

    def _initialize(self) -> None:
        with self._connect() as con:
            con.execute(_table_sql("daily_basic", DAILY_BASIC_COLUMNS, ["trade_date", "ts_code"]))
            con.execute(_table_sql("index_dailybasic", INDEX_DAILYBASIC_COLUMNS, ["trade_date", "ts_code"]))
            con.execute(_table_sql("fund_share", FUND_SHARE_COLUMNS, ["trade_date", "ts_code"]))
            con.execute(_table_sql("moneyflow_hsgt", MONEYFLOW_HSGT_COLUMNS, ["trade_date"]))
            con.execute(_table_sql("margin", MARGIN_COLUMNS, ["trade_date", "exchange_id"]))
            con.execute(_table_sql("margin_detail", MARGIN_DETAIL_COLUMNS, ["trade_date", "ts_code"]))

    def upsert_daily_basic(self, frame: pd.DataFrame) -> int:
        """幂等写入估值、市值和股息率截面。"""
        return self._upsert("daily_basic", frame, DAILY_BASIC_COLUMNS)

    def upsert_index_dailybasic(self, frame: pd.DataFrame) -> int:
        """幂等写入指数估值截面。"""
        return self._upsert("index_dailybasic", frame, INDEX_DAILYBASIC_COLUMNS)

    def upsert_fund_share(self, frame: pd.DataFrame) -> int:
        """幂等写入 ETF 份额数据。"""
        return self._upsert("fund_share", frame, FUND_SHARE_COLUMNS)

    def upsert_moneyflow_hsgt(self, frame: pd.DataFrame) -> int:
        """幂等写入北向南向资金汇总。"""
        return self._upsert("moneyflow_hsgt", frame, MONEYFLOW_HSGT_COLUMNS)

    def upsert_margin(self, frame: pd.DataFrame) -> int:
        """幂等写入两融市场汇总。"""
        return self._upsert("margin", frame, MARGIN_COLUMNS)

    def upsert_margin_detail(self, frame: pd.DataFrame) -> int:
        """幂等写入个股两融明细。"""
        return self._upsert("margin_detail", frame, MARGIN_DETAIL_COLUMNS)

    def load_table(self, table: str, trade_date: str | None = None) -> pd.DataFrame:
        """读取 beta 缓存表，供观测模块按日聚合。"""
        _ensure_table(table)
        sql = f"SELECT * FROM {table}"
        params: list[str] = []
        if trade_date is not None:
            sql += " WHERE trade_date = ?"
            params.append(str(trade_date))
        sql += " ORDER BY trade_date"
        with self._connect() as con:
            return con.execute(sql, params).fetchdf()

    def count_rows(self, table: str) -> int:
        """返回表行数，用于测试和运行验收。"""
        _ensure_table(table)
        with self._connect() as con:
            return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _upsert(self, table: str, frame: pd.DataFrame, columns: list[str]) -> int:
        clean = _normalize_frame(frame, columns)
        if clean.empty:
            return 0
        with self._connect() as con:
            con.register("input_frame", clean)
            con.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM input_frame")
        return int(len(clean))


class TushareBetaUpdater:
    """按交易日补齐 Market Beta V1 所需 P0 扩展数据。"""

    def __init__(
        self,
        client: TushareBetaClient,
        store: BetaIncrementalStore,
        fund_symbols: list[str] | None = None,
        *,
        fund_share_lookback_days: int = 14,
    ) -> None:
        if fund_share_lookback_days < 0:
            raise ValueError("fund_share_lookback_days 不能为负")
        self.client = client
        self.store = store
        self.fund_symbols = sorted(set(fund_symbols or ["510300.SH"]))
        self.fund_share_lookback_days = fund_share_lookback_days

    def update(self, trade_date: str) -> BetaUpdateResult:
        """更新指定交易日所有 P0 beta 数据源。"""
        daily_basic_rows = self.store.upsert_daily_basic(self.client.daily_basic(trade_date))
        index_dailybasic_rows = self.store.upsert_index_dailybasic(self.client.index_dailybasic(trade_date))
        fund_share_start = (
            datetime.strptime(trade_date, "%Y%m%d")
            - timedelta(days=self.fund_share_lookback_days)
        ).strftime("%Y%m%d")
        fund_share_rows = 0
        for symbol in self.fund_symbols:
            fund_share_rows += self.store.upsert_fund_share(
                self.client.fund_share(symbol, fund_share_start, trade_date)
            )
        moneyflow_hsgt_rows = self.store.upsert_moneyflow_hsgt(self.client.moneyflow_hsgt(trade_date, trade_date))
        margin_rows = self.store.upsert_margin(self.client.margin(trade_date))
        margin_detail_rows = self.store.upsert_margin_detail(self.client.margin_detail(trade_date))
        return BetaUpdateResult(
            trade_date=trade_date,
            daily_basic_rows=daily_basic_rows,
            index_dailybasic_rows=index_dailybasic_rows,
            fund_share_rows=fund_share_rows,
            moneyflow_hsgt_rows=moneyflow_hsgt_rows,
            margin_rows=margin_rows,
            margin_detail_rows=margin_detail_rows,
        )


def _table_sql(table: str, columns: list[str], primary_key: list[str]) -> str:
    """生成 DuckDB 缓存表 DDL，业务字段保持宽松浮点类型。"""
    definitions = []
    for column in columns:
        if column in {"trade_date", "ts_code", "exchange_id"}:
            definitions.append(f"{column} VARCHAR NOT NULL")
        else:
            definitions.append(f"{column} DOUBLE")
    key = ", ".join(primary_key)
    return f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(definitions)}, PRIMARY KEY ({key}))"


def _normalize_frame(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """补齐列、规范日期和数值，避免外部接口缺字段导致主流程崩坏。"""
    if frame.empty:
        return pd.DataFrame(columns=columns)
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = "" if column in {"trade_date", "ts_code", "exchange_id"} else 0.0
    result = result[columns].copy()
    for column in [item for item in columns if item in {"trade_date", "ts_code", "exchange_id"}]:
        result[column] = result[column].fillna("").astype(str)
    for column in [item for item in columns if item not in {"trade_date", "ts_code", "exchange_id"}]:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)
    keys = [item for item in ["trade_date", "ts_code", "exchange_id"] if item in columns]
    return result.drop_duplicates(keys, keep="last")


def _ensure_table(table: str) -> None:
    if table not in {
        "daily_basic",
        "index_dailybasic",
        "fund_share",
        "moneyflow_hsgt",
        "margin",
        "margin_detail",
    }:
        raise ValueError(f"不支持的 beta 表: {table}")
