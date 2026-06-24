"""Tushare ETF与指数基准增量缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd


MARKET_COLUMNS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]
FUND_ADJ_COLUMNS = ["ts_code", "trade_date", "adj_factor"]


class TushareBenchmarkClient(Protocol):
    """基准增量只依赖ETF日线、ETF复权和指数日线。"""

    def fund_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    def fund_adj(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    def index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...


class TushareBenchmarkProClient:
    """Tushare SDK 的基准行情薄封装。"""

    def __init__(self, token: str) -> None:
        if not token.strip():
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def fund_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """读取单只ETF日线。"""
        return self._pro.fund_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields=",".join(MARKET_COLUMNS),
        )

    def fund_adj(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """读取单只ETF复权因子。"""
        return self._pro.fund_adj(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields=",".join(FUND_ADJ_COLUMNS),
        )

    def index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """读取单只指数日线。"""
        return self._pro.index_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields=",".join(MARKET_COLUMNS),
        )


@dataclass(frozen=True)
class BenchmarkUpdateResult:
    """基准增量更新摘要。"""

    requested_end: str
    updated_symbols: list[str]
    fund_rows: int
    fund_adj_rows: int
    index_rows: int


class BenchmarkIncrementalStore:
    """保存ETF与指数基准增量，不改写历史基线库。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        import duckdb

        return duckdb.connect(str(self.path))

    def _initialize(self) -> None:
        with self._connect() as con:
            con.execute(_market_table_sql("fund_daily"))
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS fund_adj (
                    ts_code VARCHAR NOT NULL,
                    trade_date VARCHAR NOT NULL,
                    adj_factor DOUBLE,
                    PRIMARY KEY (ts_code, trade_date)
                )
                """
            )
            con.execute(_market_table_sql("index_daily"))

    def upsert_fund(self, frame: pd.DataFrame) -> None:
        """幂等写入ETF日线。"""
        self._upsert_market("fund_daily", frame)

    def upsert_fund_adj(self, frame: pd.DataFrame) -> None:
        """幂等写入ETF复权因子。"""
        clean = _validate_frame(frame, FUND_ADJ_COLUMNS, "fund_adj")
        with self._connect() as con:
            con.register("input_frame", clean)
            con.execute(
                """
                INSERT INTO fund_adj SELECT * FROM input_frame
                ON CONFLICT (ts_code, trade_date) DO UPDATE SET adj_factor=excluded.adj_factor
                """
            )

    def upsert_index(self, frame: pd.DataFrame) -> None:
        """幂等写入指数日线。"""
        self._upsert_market("index_daily", frame)

    def latest_date(self, table: str, ts_code: str) -> str | None:
        """读取某表某标的最大交易日。"""
        if table not in {"fund_daily", "fund_adj", "index_daily"}:
            raise ValueError(f"不支持的表: {table}")
        with self._connect() as con:
            value = con.execute(f"SELECT MAX(trade_date) FROM {table} WHERE ts_code = ?", [ts_code]).fetchone()[0]
        return str(value) if value else None

    def count_rows(self, table: str) -> int:
        """返回表行数，用于验收。"""
        if table not in {"fund_daily", "fund_adj", "index_daily"}:
            raise ValueError(f"不支持的表: {table}")
        with self._connect() as con:
            return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def load_curves(self) -> dict[str, pd.Series]:
        """从增量库导出ETF复权净值与指数净值。"""
        return {symbol: _normalize_series(series) for symbol, series in self.load_raw_series().items()}

    def load_raw_series(self) -> dict[str, pd.Series]:
        """从增量库导出未归一化的ETF复权价格与指数收盘价。"""
        curves: dict[str, pd.Series] = {}
        with self._connect() as con:
            fund = con.execute(
                """
                SELECT d.ts_code, d.trade_date, d.close, a.adj_factor
                FROM fund_daily d
                JOIN fund_adj a ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
                ORDER BY d.ts_code, d.trade_date
                """
            ).fetchdf()
            index = con.execute(
                """
                SELECT ts_code, trade_date, close
                FROM index_daily
                ORDER BY ts_code, trade_date
                """
            ).fetchdf()
        for symbol, group in fund.groupby("ts_code"):
            adjusted = group["close"].astype(float) * group["adj_factor"].astype(float)
            curves[str(symbol)] = _to_series(group["trade_date"], adjusted)
        for symbol, group in index.groupby("ts_code"):
            curves[str(symbol)] = _to_series(group["trade_date"], group["close"].astype(float))
        return curves

    def _upsert_market(self, table: str, frame: pd.DataFrame) -> None:
        clean = _validate_frame(frame, MARKET_COLUMNS, table)
        with self._connect() as con:
            con.register("input_frame", clean)
            con.execute(
                f"""
                INSERT INTO {table} SELECT * FROM input_frame
                ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, pre_close=excluded.pre_close,
                    change=excluded.change, pct_chg=excluded.pct_chg,
                    vol=excluded.vol, amount=excluded.amount
                """
            )


class TushareBenchmarkUpdater:
    """补齐 ETF 和指数基准行情。"""

    def __init__(self, client: TushareBenchmarkClient, store: BenchmarkIncrementalStore) -> None:
        self.client = client
        self.store = store

    def update(
        self,
        end_date: str,
        fund_base_latest: dict[str, str | None],
        index_base_latest: dict[str, str | None],
        default_start: str = "20150101",
    ) -> BenchmarkUpdateResult:
        """按标的从最新缓存或基线之后继续拉取。"""
        updated: list[str] = []
        fund_rows = 0
        fund_adj_rows = 0
        index_rows = 0
        for symbol, base_latest in fund_base_latest.items():
            start = _resolve_start(base_latest, self.store.latest_date("fund_daily", symbol), default_start)
            if start > end_date:
                continue
            daily = self.client.fund_daily(symbol, start, end_date)
            factors = self.client.fund_adj(symbol, start, end_date)
            if not daily.empty and not factors.empty:
                self.store.upsert_fund(daily)
                self.store.upsert_fund_adj(factors)
                updated.append(symbol)
                fund_rows += len(daily)
                fund_adj_rows += len(factors)
        for symbol, base_latest in index_base_latest.items():
            start = _resolve_start(base_latest, self.store.latest_date("index_daily", symbol), default_start)
            if start > end_date:
                continue
            daily = self.client.index_daily(symbol, start, end_date)
            if not daily.empty:
                self.store.upsert_index(daily)
                updated.append(symbol)
                index_rows += len(daily)
        return BenchmarkUpdateResult(end_date, updated, fund_rows, fund_adj_rows, index_rows)


def _market_table_sql(table: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table} (
            ts_code VARCHAR NOT NULL,
            trade_date VARCHAR NOT NULL,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
            pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE,
            vol DOUBLE, amount DOUBLE,
            PRIMARY KEY (ts_code, trade_date)
        )
        """


def _validate_frame(frame: pd.DataFrame, columns: list[str], label: str) -> pd.DataFrame:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} 缺少字段: {missing}")
    result = frame[columns].copy()
    result["ts_code"] = result["ts_code"].astype(str)
    result["trade_date"] = result["trade_date"].astype(str)
    return result.drop_duplicates(["ts_code", "trade_date"], keep="last")


def _to_series(dates: pd.Series, values: pd.Series) -> pd.Series:
    result = pd.Series(values.astype(float).values, index=pd.to_datetime(dates, format="%Y%m%d"))
    return result.sort_index()


def _normalize_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    return series / float(series.iloc[0])


def _next_date(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def _resolve_start(base_latest: str | None, cache_latest: str | None, default_start: str) -> str:
    latest = max(filter(None, [base_latest, cache_latest]), default=None)
    return _next_date(latest) if latest else default_start
