"""
ETF/LOF/REITs DuckDB 数据源适配。

用于把基金基础信息和复权日线接入统一行情 schema，可作为沪深300
ETF 基准和基金类标的研究的数据入口。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data.cleaning import clean_daily_bars


class DuckDBFundDataSource:
    """本地 ETF/LOF/REITs DuckDB 适配器。"""

    DAILY_TABLE = "etf_lof_reits_daily_adj"
    BASIC_TABLE = "etf_lof_reits_basic_export"

    def __init__(self, daily_db_path: str | Path, basic_db_path: str | Path | None = None):
        self.daily_db_path = Path(daily_db_path)
        self.basic_db_path = Path(basic_db_path) if basic_db_path is not None else None
        if not self.daily_db_path.exists():
            raise FileNotFoundError(f"基金日线 DuckDB 文件不存在: {self.daily_db_path}")
        if self.basic_db_path is not None and not self.basic_db_path.exists():
            raise FileNotFoundError(f"基金基础 DuckDB 文件不存在: {self.basic_db_path}")

    def _connect(self, path: Path):
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError("缺少 duckdb 依赖，请先安装: python -m pip install duckdb") from exc
        return duckdb.connect(str(path), read_only=True)

    def get_daily_bars(
        self,
        symbol: str,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """读取基金复权日线并输出统一 schema。"""
        where = ["ts_code = ?"]
        params = [symbol]
        if start_date is not None:
            where.append("trade_date >= ?")
            params.append(self._format_date(start_date))
        if end_date is not None:
            where.append("trade_date <= ?")
            params.append(self._format_date(end_date))
        with self._connect(self.daily_db_path) as con:
            frame = con.execute(
                f"""
                SELECT
                  trade_date,
                  ts_code AS symbol,
                  ts_code AS code,
                  open,
                  high,
                  low,
                  close,
                  vol AS volume,
                  amount,
                  adj_factor,
                  fund_name,
                  exchange,
                  fund_category
                FROM "{self.DAILY_TABLE}"
                WHERE {" AND ".join(where)}
                ORDER BY trade_date
                """,
                params,
            ).fetchdf()
        if not frame.empty:
            frame["is_suspended"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0) <= 0
            frame["limit_up"] = False
            frame["limit_down"] = False
        result = clean_daily_bars(frame, symbol=symbol)
        result.attrs["source"] = "fund_duckdb"
        result.attrs["adjust"] = "provider_adjusted"
        return result

    def get_fund_basic(self) -> pd.DataFrame:
        """读取基金基础信息。"""
        if self.basic_db_path is None:
            return pd.DataFrame()
        with self._connect(self.basic_db_path) as con:
            return con.execute(f'SELECT * FROM "{self.BASIC_TABLE}" ORDER BY ts_code').fetchdf()

    def find_funds(self, keyword: str) -> pd.DataFrame:
        """按名称、指数代码、指数名称搜索基金。"""
        basic = self.get_fund_basic()
        if basic.empty:
            return basic
        keyword = str(keyword)
        mask = pd.Series(False, index=basic.index)
        for column in ["name", "full_name", "index_code", "index_name", "fund_category"]:
            if column in basic.columns:
                mask = mask | basic[column].fillna("").astype(str).str.contains(keyword, case=False, regex=False)
        return basic[mask].reset_index(drop=True)

    def _format_date(self, value: str | pd.Timestamp) -> str:
        text = str(value)
        if len(text) == 8 and text.isdigit():
            return text
        return pd.Timestamp(value).strftime("%Y%m%d")
