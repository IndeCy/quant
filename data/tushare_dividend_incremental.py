"""Tushare 标准分红数据增量缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd


DIVIDEND_COLUMNS = [
    "ts_code", "end_date", "ann_date", "div_proc", "stk_div", "stk_bo_rate",
    "stk_co_rate", "cash_div", "cash_div_tax", "record_date", "ex_date",
    "pay_date", "div_listdate", "imp_ann_date", "base_date", "base_share",
]


class TushareDividendClient(Protocol):
    """分红接口协议，便于测试注入。"""

    def dividend(self, ann_date: str) -> pd.DataFrame: ...


class TushareDividendProClient:
    """Tushare dividend 接口薄封装。"""

    def __init__(self, token: str) -> None:
        if not token.strip():
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def dividend(self, ann_date: str) -> pd.DataFrame:
        """按公告日获取全市场分红记录。"""
        return self._pro.dividend(ann_date=ann_date, fields=",".join(DIVIDEND_COLUMNS))


@dataclass(frozen=True)
class DividendUpdateResult:
    """分红增量更新摘要。"""

    requested_start: str
    requested_end: str
    updated_dates: list[str]
    rows: int


class DividendDuckDBStore:
    """保存标准分红记录，不改写行情或财务基线库。"""

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
                CREATE TABLE IF NOT EXISTS dividend (
                    ts_code VARCHAR NOT NULL,
                    end_date VARCHAR,
                    ann_date VARCHAR NOT NULL,
                    div_proc VARCHAR NOT NULL,
                    stk_div DOUBLE,
                    stk_bo_rate DOUBLE,
                    stk_co_rate DOUBLE,
                    cash_div DOUBLE,
                    cash_div_tax DOUBLE,
                    record_date VARCHAR,
                    ex_date VARCHAR,
                    pay_date VARCHAR,
                    div_listdate VARCHAR,
                    imp_ann_date VARCHAR,
                    base_date VARCHAR,
                    base_share DOUBLE,
                    PRIMARY KEY (ts_code, end_date, ann_date, div_proc)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS dividend_update_log (
                    ann_date VARCHAR PRIMARY KEY,
                    row_count INTEGER NOT NULL,
                    checked_at VARCHAR NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def upsert(self, frame: pd.DataFrame) -> None:
        """幂等写入分红记录。"""
        clean = _validate_frame(frame)
        if clean.empty:
            return
        with self._connect() as con:
            con.register("input_frame", clean)
            con.execute(
                """
                INSERT INTO dividend SELECT * FROM input_frame
                ON CONFLICT (ts_code, end_date, ann_date, div_proc) DO UPDATE SET
                    stk_div=excluded.stk_div,
                    stk_bo_rate=excluded.stk_bo_rate,
                    stk_co_rate=excluded.stk_co_rate,
                    cash_div=excluded.cash_div,
                    cash_div_tax=excluded.cash_div_tax,
                    record_date=excluded.record_date,
                    ex_date=excluded.ex_date,
                    pay_date=excluded.pay_date,
                    div_listdate=excluded.div_listdate,
                    imp_ann_date=excluded.imp_ann_date,
                    base_date=excluded.base_date,
                    base_share=excluded.base_share
                """
            )

    def load(self) -> pd.DataFrame:
        """读取全部分红缓存。"""
        with self._connect() as con:
            return con.execute("SELECT * FROM dividend ORDER BY ann_date, ts_code, div_proc").fetchdf()

    def count_rows(self) -> int:
        """返回缓存行数。"""
        with self._connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM dividend").fetchone()[0])

    def latest_ann_date(self) -> str | None:
        """读取已缓存最大公告日。"""
        with self._connect() as con:
            value = con.execute(
                """
                SELECT MAX(ann_date) FROM (
                    SELECT ann_date FROM dividend
                    UNION ALL
                    SELECT ann_date FROM dividend_update_log
                )
                """
            ).fetchone()[0]
        return str(value) if value else None

    def mark_checked(self, ann_date: str, row_count: int) -> None:
        """记录公告日已检查，空结果也不重复请求。"""
        checked_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO dividend_update_log(ann_date, row_count, checked_at)
                VALUES (?, ?, ?)
                ON CONFLICT (ann_date) DO UPDATE SET
                    row_count=excluded.row_count,
                    checked_at=excluded.checked_at
                """,
                [ann_date, int(row_count), checked_at],
            )


class TushareDividendUpdater:
    """按公告日增量补齐分红缓存。"""

    def __init__(self, client: TushareDividendClient, store: DividendDuckDBStore, start_date: str = "20150101") -> None:
        self.client = client
        self.store = store
        self.start_date = start_date

    def update_through(self, end_date: str) -> DividendUpdateResult:
        """逐自然日按 ann_date 拉取，空结果也视为已检查但不落表。"""
        latest = self.store.latest_ann_date()
        start = _next_date(latest) if latest else self.start_date
        if start > end_date:
            return DividendUpdateResult(start, end_date, [], 0)
        updated: list[str] = []
        rows = 0
        for ann_date in _date_range(start, end_date):
            frame = self.client.dividend(ann_date)
            if not frame.empty:
                self.store.upsert(frame)
                updated.append(ann_date)
                rows += len(frame)
            self.store.mark_checked(ann_date, len(frame))
        return DividendUpdateResult(start, end_date, updated, rows)


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in DIVIDEND_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"分红数据缺少字段: {missing}")
    result = frame[DIVIDEND_COLUMNS].copy()
    for column in ["ts_code", "end_date", "ann_date", "div_proc"]:
        result[column] = result[column].astype(str)
    return result.drop_duplicates(["ts_code", "end_date", "ann_date", "div_proc"], keep="last")


def _next_date(value: str) -> str:
    return (datetime.strptime(value, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def _date_range(start: str, end: str) -> list[str]:
    start_dt = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    days = (end_dt - start_dt).days
    return [(start_dt + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days + 1)]
