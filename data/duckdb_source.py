"""
DuckDB A股历史数据适配层。

该模块是项目访问 DuckDB 的唯一入口。回测、策略和因子层只能读取这里输出的
统一 schema，不能直接依赖 DuckDB 表结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from data.adjustment import AdjustType, normalize_adjust
from data.calendar import TradingCalendar
from data.cleaning import clean_daily_bars
from data.financial import FinancialDataPortal
from data.financial_duckdb_source import DuckDBFinancialDataSource


DEFAULT_DUCKDB_PATH = Path(__file__).resolve().parents[2] / "database" / "daily_adj_19901219_20260615.duckdb"


@dataclass(frozen=True)
class DuckDBTableSummary:
    """DuckDB 表结构摘要。"""

    table_name: str
    columns: list[tuple[str, str]]
    row_count: int
    date_ranges: dict[str, tuple[object, object]]


class DuckDBAshareDataSource:
    """基于 DuckDB 的 A 股数据源，输出项目统一日线 schema。"""

    DAILY_TABLE = "daily"
    ADJ_CACHE_TABLE = "daily_adj_cache"
    ADJ_FACTOR_TABLE = "adj_factor"
    STOCK_BASIC_TABLE = "stock_basic"
    STOCK_ST_TABLE = "stock_st"

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        financial_db_paths: dict[str, str | Path] | None = None,
    ):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"DuckDB 数据文件不存在: {self.db_path}")
        self.financial_db_paths = financial_db_paths or {}

    def _connect(self):
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError("缺少 duckdb 依赖，请先安装: python -m pip install duckdb") from exc
        return duckdb.connect(str(self.db_path), read_only=True)

    def inspect_tables(self) -> list[DuckDBTableSummary]:
        """读取所有表名、字段、数据量和候选日期范围。"""
        with self._connect() as con:
            tables = con.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ).fetchall()
            summaries: list[DuckDBTableSummary] = []
            for (table_name,) in tables:
                columns = con.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'main' AND table_name = ?
                    ORDER BY ordinal_position
                    """,
                    [table_name],
                ).fetchall()
                row_count = int(con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])
                date_ranges: dict[str, tuple[object, object]] = {}
                for column_name, _ in columns:
                    lower_name = column_name.lower()
                    if "date" not in lower_name and "time" not in lower_name and "day" not in lower_name:
                        continue
                    min_value, max_value = con.execute(
                        f'SELECT MIN("{column_name}"), MAX("{column_name}") FROM "{table_name}"'
                    ).fetchone()
                    date_ranges[column_name] = (min_value, max_value)
                summaries.append(DuckDBTableSummary(table_name, columns, row_count, date_ranges))
            return summaries

    def get_trading_calendar(
        self,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
    ) -> TradingCalendar:
        """从 daily 表真实交易日期派生交易日历。"""
        where, params = self._date_filter_sql(start_date, end_date, table_alias="")
        sql = f'SELECT DISTINCT trade_date FROM "{self.DAILY_TABLE}" {where} ORDER BY trade_date'
        with self._connect() as con:
            dates = con.execute(sql, params).fetchdf()["trade_date"]
        return TradingCalendar(pd.to_datetime(dates, format="%Y%m%d"))

    def get_daily_bars(
        self,
        symbol: str,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
        adjust_policy: str | AdjustType = AdjustType.NONE,
    ) -> pd.DataFrame:
        """
        读取日线行情并统一到 data/schema.py。

        adjust_policy 必须显式传入并与读取表字段匹配。none 读取原始 daily；
        qfq/hfq 读取 daily_adj_cache 中对应复权价格，并保留原始成交量、成交额。
        """
        adjust = normalize_adjust(adjust_policy)
        with self._connect() as con:
            if adjust == AdjustType.NONE:
                frame = self._read_raw_daily(con, symbol, start_date, end_date)
            elif adjust in {AdjustType.QFQ, AdjustType.HFQ}:
                frame = self._read_adjusted_daily(con, symbol, start_date, end_date, adjust)
            else:
                raise ValueError(f"不支持的复权口径: {adjust_policy}")

        if frame.empty:
            result = clean_daily_bars(frame, symbol=symbol)
            result.attrs["adjust"] = adjust.value
            result.attrs["source"] = "duckdb"
            return result

        frame = self._append_limit_flags(frame)
        result = clean_daily_bars(frame, symbol=symbol)
        result.attrs["adjust"] = adjust.value
        result.attrs["source"] = "duckdb"
        result.attrs["limit_flags"] = "derived_from_pre_close_and_st_status"
        result.attrs["is_suspended"] = "derived_from_volume_or_missing_bar"
        return result

    def get_stock_basic(self) -> pd.DataFrame:
        """读取股票基础信息。"""
        with self._connect() as con:
            return con.execute(f'SELECT * FROM "{self.STOCK_BASIC_TABLE}" ORDER BY ts_code').fetchdf()

    def get_daily_bars_many(
        self,
        symbols: Iterable[str],
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
        adjust_policy: str | AdjustType = AdjustType.NONE,
    ) -> dict[str, pd.DataFrame]:
        """批量读取多只股票日线，仍按单标的输出统一 schema。"""
        symbol_list = list(symbols)
        if not symbol_list:
            return {}

        adjust = normalize_adjust(adjust_policy)
        placeholders = ", ".join(["?"] * len(symbol_list))
        with self._connect() as con:
            if adjust == AdjustType.NONE:
                frame = self._read_raw_daily_many(con, symbol_list, placeholders, start_date, end_date)
            elif adjust in {AdjustType.QFQ, AdjustType.HFQ}:
                frame = self._read_adjusted_daily_many(con, symbol_list, placeholders, start_date, end_date, adjust)
            else:
                raise ValueError(f"不支持的复权口径: {adjust_policy}")

        results: dict[str, pd.DataFrame] = {}
        if frame.empty:
            for symbol in symbol_list:
                empty = clean_daily_bars(frame, symbol=symbol)
                empty.attrs["adjust"] = adjust.value
                empty.attrs["source"] = "duckdb"
                results[symbol] = empty
            return results

        frame = self._append_limit_flags(frame)
        for symbol, group in frame.groupby("symbol", sort=False):
            bars = clean_daily_bars(group.copy(), symbol=str(symbol))
            bars.attrs["adjust"] = adjust.value
            bars.attrs["source"] = "duckdb"
            bars.attrs["limit_flags"] = "derived_from_pre_close_and_st_status"
            bars.attrs["is_suspended"] = "derived_from_volume_or_missing_bar"
            results[str(symbol)] = bars
        return results

    def get_financial_portal(
        self,
        fields_by_statement: dict[str, Iterable[str]] | None = None,
    ) -> FinancialDataPortal:
        """读取已挂载财务 DuckDB，并构造 as-of 财务门面。"""
        if self.financial_db_paths:
            return DuckDBFinancialDataSource(self.financial_db_paths).get_financial_portal(fields_by_statement)
        raise ValueError(
            "DuckDB 数据库未发现财务表及 publish_date/ann_date 字段，"
            "不能提供 as-of 财务查询。"
        )

    def _read_raw_daily(
        self,
        con,
        symbol: str,
        start_date: str | pd.Timestamp | None,
        end_date: str | pd.Timestamp | None,
    ) -> pd.DataFrame:
        where, params = self._date_filter_sql(start_date, end_date, table_alias="d")
        params = [symbol, *params]
        sql = f"""
            SELECT
                d.trade_date,
                d.ts_code AS symbol,
                d.ts_code AS code,
                d.open,
                d.high,
                d.low,
                d.close,
                d.vol AS volume,
                d.amount,
                af.adj_factor,
                d.pre_close,
                st.name AS st_name
            FROM "{self.DAILY_TABLE}" d
            LEFT JOIN "{self.ADJ_FACTOR_TABLE}" af
              ON d.ts_code = af.ts_code AND d.trade_date = af.trade_date
            LEFT JOIN "{self.STOCK_ST_TABLE}" st
              ON d.ts_code = st.ts_code AND d.trade_date = st.trade_date
            WHERE d.ts_code = ?
            {where.replace("WHERE", "AND", 1) if where else ""}
            ORDER BY d.trade_date
        """
        return con.execute(sql, params).fetchdf()

    def _read_adjusted_daily(
        self,
        con,
        symbol: str,
        start_date: str | pd.Timestamp | None,
        end_date: str | pd.Timestamp | None,
        adjust: AdjustType,
    ) -> pd.DataFrame:
        suffix = adjust.value
        required_columns = [f"open_{suffix}", f"high_{suffix}", f"low_{suffix}", f"close_{suffix}"]
        available = {
            row[0]
            for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [self.ADJ_CACHE_TABLE],
            ).fetchall()
        }
        missing = [column for column in required_columns if column not in available]
        if missing:
            raise ValueError(f"DuckDB 复权缓存缺少字段，不能读取 {adjust.value}: {missing}")

        where, params = self._date_filter_sql(start_date, end_date, table_alias="a")
        params = [symbol, *params]
        sql = f"""
            SELECT
                a.trade_date,
                a.ts_code AS symbol,
                a.ts_code AS code,
                a.open_{suffix} AS open,
                a.high_{suffix} AS high,
                a.low_{suffix} AS low,
                a.close_{suffix} AS close,
                d.vol AS volume,
                d.amount,
                a.adj_factor,
                a.pre_close_{suffix} AS pre_close,
                st.name AS st_name
            FROM "{self.ADJ_CACHE_TABLE}" a
            LEFT JOIN "{self.DAILY_TABLE}" d
              ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date
            LEFT JOIN "{self.STOCK_ST_TABLE}" st
              ON a.ts_code = st.ts_code AND a.trade_date = st.trade_date
            WHERE a.ts_code = ?
            {where.replace("WHERE", "AND", 1) if where else ""}
            ORDER BY a.trade_date
        """
        return con.execute(sql, params).fetchdf()

    def _read_raw_daily_many(
        self,
        con,
        symbols: list[str],
        placeholders: str,
        start_date: str | pd.Timestamp | None,
        end_date: str | pd.Timestamp | None,
    ) -> pd.DataFrame:
        where, params = self._date_filter_sql(start_date, end_date, table_alias="d")
        params = [*symbols, *params]
        sql = f"""
            SELECT
                d.trade_date,
                d.ts_code AS symbol,
                d.ts_code AS code,
                d.open,
                d.high,
                d.low,
                d.close,
                d.vol AS volume,
                d.amount,
                af.adj_factor,
                d.pre_close,
                st.name AS st_name
            FROM "{self.DAILY_TABLE}" d
            LEFT JOIN "{self.ADJ_FACTOR_TABLE}" af
              ON d.ts_code = af.ts_code AND d.trade_date = af.trade_date
            LEFT JOIN "{self.STOCK_ST_TABLE}" st
              ON d.ts_code = st.ts_code AND d.trade_date = st.trade_date
            WHERE d.ts_code IN ({placeholders})
            {where.replace("WHERE", "AND", 1) if where else ""}
            ORDER BY d.ts_code, d.trade_date
        """
        return con.execute(sql, params).fetchdf()

    def _read_adjusted_daily_many(
        self,
        con,
        symbols: list[str],
        placeholders: str,
        start_date: str | pd.Timestamp | None,
        end_date: str | pd.Timestamp | None,
        adjust: AdjustType,
    ) -> pd.DataFrame:
        suffix = adjust.value
        where, params = self._date_filter_sql(start_date, end_date, table_alias="a")
        params = [*symbols, *params]
        sql = f"""
            SELECT
                a.trade_date,
                a.ts_code AS symbol,
                a.ts_code AS code,
                a.open_{suffix} AS open,
                a.high_{suffix} AS high,
                a.low_{suffix} AS low,
                a.close_{suffix} AS close,
                d.vol AS volume,
                d.amount,
                a.adj_factor,
                a.pre_close_{suffix} AS pre_close,
                st.name AS st_name
            FROM "{self.ADJ_CACHE_TABLE}" a
            LEFT JOIN "{self.DAILY_TABLE}" d
              ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date
            LEFT JOIN "{self.STOCK_ST_TABLE}" st
              ON a.ts_code = st.ts_code AND a.trade_date = st.trade_date
            WHERE a.ts_code IN ({placeholders})
            {where.replace("WHERE", "AND", 1) if where else ""}
            ORDER BY a.ts_code, a.trade_date
        """
        return con.execute(sql, params).fetchdf()

    def _append_limit_flags(self, frame: pd.DataFrame) -> pd.DataFrame:
        """根据昨收和 ST 状态推导涨跌停标记，并保留可审计来源。"""
        result = frame.copy()
        pre_close = pd.to_numeric(result.get("pre_close"), errors="coerce")
        st_name = result.get("st_name", pd.Series("", index=result.index)).fillna("").astype(str)
        is_st = st_name.str.contains("ST|退", regex=True)
        code = result["symbol"].astype(str)
        limit_rate = pd.Series(0.10, index=result.index)
        limit_rate.loc[is_st] = 0.05
        limit_rate.loc[code.str.startswith(("300", "301", "688", "689"))] = 0.20
        limit_rate.loc[code.str.startswith(("8", "4", "920"))] = 0.30

        upper = (pre_close * (1 + limit_rate)).round(2)
        lower = (pre_close * (1 - limit_rate)).round(2)
        high = pd.to_numeric(result["high"], errors="coerce")
        low = pd.to_numeric(result["low"], errors="coerce")
        result["limit_up"] = high.notna() & upper.notna() & (high >= upper - 1e-6)
        result["limit_down"] = low.notna() & lower.notna() & (low <= lower + 1e-6)
        result["is_suspended"] = pd.to_numeric(result.get("volume"), errors="coerce").fillna(0) <= 0
        return result

    def _date_filter_sql(
        self,
        start_date: str | pd.Timestamp | None,
        end_date: str | pd.Timestamp | None,
        table_alias: str = "",
    ) -> tuple[str, list[str]]:
        prefix = f"{table_alias}." if table_alias else ""
        clauses: list[str] = []
        params: list[str] = []
        if start_date is not None:
            clauses.append(f"{prefix}trade_date >= ?")
            params.append(self._format_trade_date(start_date))
        if end_date is not None:
            clauses.append(f"{prefix}trade_date <= ?")
            params.append(self._format_trade_date(end_date))
        if not clauses:
            return "", []
        return "WHERE " + " AND ".join(clauses), params

    def _format_trade_date(self, value: str | pd.Timestamp) -> str:
        text = str(value)
        if len(text) == 8 and text.isdigit():
            return text
        return pd.Timestamp(value).strftime("%Y%m%d")


def summarize_capabilities(table_summaries: Iterable[DuckDBTableSummary]) -> dict[str, bool]:
    """根据表和字段快速判断数据覆盖能力。"""
    table_map = {summary.table_name: {name for name, _ in summary.columns} for summary in table_summaries}
    financial_tables = {
        name: columns
        for name, columns in table_map.items()
        if any(keyword in name.lower() for keyword in ["financial", "finance", "income", "balance", "cashflow", "fina"])
    }
    return {
        "日线行情": "daily" in table_map,
        "股票基础信息": "stock_basic" in table_map,
        "交易日历": "daily" in table_map,
        "ST/退市状态": "stock_st" in table_map or "stock_namechange" in table_map or "stock_basic" in table_map,
        "财务数据": bool(financial_tables),
        "财务公告日": any({"publish_date", "ann_date"} & columns for columns in financial_tables.values()),
        "分红数据": False,
        "行业分类": False,
        "指数行情/沪深300": False,
    }
