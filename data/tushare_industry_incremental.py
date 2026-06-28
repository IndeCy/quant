"""Tushare 行业基础信息增量缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os

import duckdb
import pandas as pd


INDUSTRY_COLUMNS = ["ts_code", "symbol", "name", "area", "industry", "market", "list_date", "list_status"]


@dataclass(frozen=True)
class IndustryUpdateResult:
    """行业缓存更新结果。"""

    row_count: int
    updated_at: str


class TushareIndustryProClient:
    """Tushare 行业基础信息客户端。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def stock_basic(self) -> pd.DataFrame:
        """读取股票基础行业信息。"""
        return self._pro.stock_basic(exchange="", list_status="L", fields=",".join(INDUSTRY_COLUMNS))


class IndustryDuckDBStore:
    """本地行业缓存。"""

    def __init__(self, db_path: str | Path = "data/industry_increment.duckdb") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path))

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_industry (
                    ts_code VARCHAR PRIMARY KEY,
                    symbol VARCHAR,
                    name VARCHAR,
                    area VARCHAR,
                    industry VARCHAR,
                    market VARCHAR,
                    list_date VARCHAR,
                    list_status VARCHAR,
                    updated_at VARCHAR
                )
                """
            )

    def upsert(self, frame: pd.DataFrame) -> IndustryUpdateResult:
        """覆盖写入最新静态行业信息。"""
        missing = [column for column in INDUSTRY_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"缺少行业字段: {missing}")
        updated_at = datetime.now().isoformat(timespec="seconds")
        data = frame[INDUSTRY_COLUMNS].copy()
        data["updated_at"] = updated_at
        with self._connect() as con:
            con.register("industry_input", data)
            con.execute(
                """
                INSERT OR REPLACE INTO stock_industry
                SELECT * FROM industry_input
                """
            )
        return IndustryUpdateResult(row_count=len(data), updated_at=updated_at)

    def load(self) -> pd.DataFrame:
        """读取行业缓存。"""
        with self._connect() as con:
            return con.execute("SELECT * FROM stock_industry ORDER BY ts_code").fetchdf()


def update_tushare_industry_cache(db_path: str | Path = "data/industry_increment.duckdb") -> IndustryUpdateResult:
    """从 Tushare 更新行业基础信息缓存。"""
    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        raise RuntimeError("未检测到TUSHARE_TOKEN，无法更新行业数据")
    client = TushareIndustryProClient(token)
    return IndustryDuckDBStore(db_path).upsert(client.stock_basic())
