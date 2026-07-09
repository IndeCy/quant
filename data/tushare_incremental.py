"""Tushare A股日线与复权因子的按交易日增量缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd

from data.calendar import TradingCalendar


DAILY_COLUMNS = [
    "ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
    "change", "pct_chg", "vol", "amount",
]
FACTOR_COLUMNS = ["ts_code", "trade_date", "adj_factor"]


class TushareDailyClient(Protocol):
    """增量更新只依赖三个按日期截面接口。"""

    def trade_cal(self, start_date: str, end_date: str) -> pd.DataFrame: ...

    def daily(self, trade_date: str) -> pd.DataFrame: ...

    def adj_factor(self, trade_date: str) -> pd.DataFrame: ...


class TushareProClient:
    """对 Tushare SDK 做最薄封装，便于测试注入假客户端。"""

    def __init__(self, token: str) -> None:
        if not token.strip():
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def trade_cal(self, start_date: str, end_date: str) -> pd.DataFrame:
        """读取上交所交易日历。"""
        return self._pro.trade_cal(
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
            fields="cal_date,is_open,pretrade_date",
        )

    def daily(self, trade_date: str) -> pd.DataFrame:
        """一次获取指定交易日全部A股日线。"""
        return self._pro.daily(trade_date=trade_date, fields=",".join(DAILY_COLUMNS))

    def adj_factor(self, trade_date: str) -> pd.DataFrame:
        """一次获取指定交易日全部A股复权因子。"""
        return self._pro.adj_factor(trade_date=trade_date, fields=",".join(FACTOR_COLUMNS))


@dataclass(frozen=True)
class IncrementalUpdateResult:
    """单次增量更新摘要。"""

    requested_start: str
    requested_end: str
    updated_dates: list[str]
    daily_rows: int
    factor_rows: int


class IncrementalDuckDBStore:
    """保存新增行情，不修改用户提供的历史基线库。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        import duckdb

        return duckdb.connect(str(self.path))

    def _initialize(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS daily (
                    ts_code VARCHAR NOT NULL,
                    trade_date VARCHAR NOT NULL,
                    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                    pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE,
                    vol DOUBLE, amount DOUBLE,
                    PRIMARY KEY (ts_code, trade_date)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS adj_factor (
                    ts_code VARCHAR NOT NULL,
                    trade_date VARCHAR NOT NULL,
                    adj_factor DOUBLE,
                    PRIMARY KEY (ts_code, trade_date)
                )
                """
            )

    def latest_date(self, table: str = "daily") -> str | None:
        """读取增量表当前最大交易日。"""
        if table not in {"daily", "adj_factor"}:
            raise ValueError(f"不支持的表: {table}")
        with self._connect() as con:
            value = con.execute(f"SELECT MAX(trade_date) FROM {table}").fetchone()[0]
        return str(value) if value else None

    def contains_date(self, trade_date: str) -> bool:
        """行情与复权因子都存在时才认为当日缓存完整。"""
        with self._connect() as con:
            daily_count = con.execute("SELECT COUNT(*) FROM daily WHERE trade_date = ?", [trade_date]).fetchone()[0]
            factor_count = con.execute("SELECT COUNT(*) FROM adj_factor WHERE trade_date = ?", [trade_date]).fetchone()[0]
        return daily_count > 0 and factor_count > 0

    def upsert(self, daily: pd.DataFrame, factors: pd.DataFrame) -> None:
        """事务内幂等写入日线和复权因子。"""
        clean_daily = _validate_frame(daily, DAILY_COLUMNS, "daily")
        clean_factors = _validate_frame(factors, FACTOR_COLUMNS, "adj_factor")
        with self._connect() as con:
            con.register("daily_input", clean_daily)
            con.register("factor_input", clean_factors)
            con.execute(
                """
                INSERT INTO daily SELECT * FROM daily_input
                ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                    pre_close=excluded.pre_close, change=excluded.change, pct_chg=excluded.pct_chg,
                    vol=excluded.vol, amount=excluded.amount
                """
            )
            con.execute(
                """
                INSERT INTO adj_factor SELECT * FROM factor_input
                ON CONFLICT (ts_code, trade_date) DO UPDATE SET adj_factor=excluded.adj_factor
                """
            )

    def count_rows(self, table: str) -> int:
        """测试和运行验收使用的行数统计。"""
        if table not in {"daily", "adj_factor"}:
            raise ValueError(f"不支持的表: {table}")
        with self._connect() as con:
            return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


class TushareDailyUpdater:
    """从历史库末日之后，仅补拉已收盘的真实交易日。"""

    def __init__(
        self,
        client: TushareDailyClient,
        store: IncrementalDuckDBStore,
        base_latest_date: str,
        market_close_time: time = time(15, 30),
    ) -> None:
        self.client = client
        self.store = store
        self.base_latest_date = base_latest_date
        self.market_close_time = market_close_time

    def update_through(self, end_date: str, now: datetime | None = None) -> IncrementalUpdateResult:
        """更新至目标日期；盘中运行时自动排除当天。"""
        current = now or datetime.now()
        # 从历史基线后一日开始扫描，才能发现增量库中间缺口。
        # 已存在的完整日期由 store.contains_date 跳过，避免重复写入。
        start = (datetime.strptime(self.base_latest_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        if start > end_date:
            return IncrementalUpdateResult(start, end_date, [], 0, 0)

        open_dates = self._load_open_dates(start, end_date, current)
        updated: list[str] = []
        daily_rows = 0
        factor_rows = 0
        for trade_date in open_dates:
            if self.store.contains_date(trade_date):
                continue
            daily = self.client.daily(trade_date)
            factors = self.client.adj_factor(trade_date)
            if daily.empty or factors.empty:
                raise RuntimeError(f"{trade_date} 行情或复权因子为空，拒绝写入不完整缓存")
            self.store.upsert(daily, factors)
            updated.append(trade_date)
            daily_rows += len(daily)
            factor_rows += len(factors)
        return IncrementalUpdateResult(start, end_date, updated, daily_rows, factor_rows)

    def _load_open_dates(self, start_date: str, end_date: str, now: datetime) -> list[str]:
        """优先走 Tushare 交易日历，频控时回退本地 A 股交易日历。"""
        try:
            calendar = self.client.trade_cal(start_date, end_date)
            return sorted(
                str(value)
                for value in calendar.loc[calendar["is_open"].astype(int).eq(1), "cal_date"]
                if start_date <= str(value) <= end_date
                and _is_complete_date(str(value), now, self.market_close_time)
            )
        except Exception:
            # quality 盘后补库只需要“哪些天已经完整收盘”，本地交易日历足够覆盖
            # 这一步，避免 trade_cal 频控时整次更新直接失效。
            calendar = TradingCalendar()
            return [
                day.strftime("%Y%m%d")
                for day in calendar.trading_days(
                    datetime.strptime(start_date, "%Y%m%d"),
                    datetime.strptime(end_date, "%Y%m%d"),
                )
                if _is_complete_date(day.strftime("%Y%m%d"), now, self.market_close_time)
            ]


def _is_complete_date(trade_date: str, now: datetime, close_time: time) -> bool:
    """历史日期均完整，当天必须等到收盘后。"""
    date_value = datetime.strptime(trade_date, "%Y%m%d").date()
    return date_value < now.date() or (date_value == now.date() and now.time() >= close_time)


def _validate_frame(frame: pd.DataFrame, columns: list[str], label: str) -> pd.DataFrame:
    """统一列顺序、主键格式和重复记录。"""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} 缺少字段: {missing}")
    result = frame[columns].copy()
    result["ts_code"] = result["ts_code"].astype(str)
    result["trade_date"] = result["trade_date"].astype(str)
    return result.drop_duplicates(["ts_code", "trade_date"], keep="last")
