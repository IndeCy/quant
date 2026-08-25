"""低频研究统一使用的前复权行情特征门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


class DuckDBConnection(Protocol):
    """声明行情特征查询需要的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_market_features(
    connection: DuckDBConnection,
    *,
    lookback_start: str = "20140701",
    research_start: str = "20150101",
) -> None:
    """创建研究特征临时表，价格字段统一为 qfq。"""
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE features AS
        WITH bars AS (
            SELECT
                a.ts_code AS symbol,
                a.trade_date,
                a.open_qfq AS open,
                a.high_qfq AS high,
                a.low_qfq AS low,
                a.close_qfq AS close,
                a.pre_close_qfq AS pre_close,
                d.close AS raw_close,
                a.adj_factor,
                d.vol AS volume,
                d.amount,
                st.name AS st_name,
                LAG(a.close_qfq) OVER(PARTITION BY a.ts_code ORDER BY a.trade_date) AS prev_close,
                LAG(a.close_qfq, 20) OVER(PARTITION BY a.ts_code ORDER BY a.trade_date) AS close_20,
                LAG(a.close_qfq, 120) OVER(PARTITION BY a.ts_code ORDER BY a.trade_date) AS close_120,
                AVG(a.close_qfq) OVER(
                    PARTITION BY a.ts_code ORDER BY a.trade_date
                    ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                ) AS ma60,
                AVG(a.close_qfq) OVER(
                    PARTITION BY a.ts_code ORDER BY a.trade_date
                    ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
                ) AS ma120,
                AVG(d.amount) OVER(
                    PARTITION BY a.ts_code ORDER BY a.trade_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS amount20,
                AVG(d.amount) OVER(
                    PARTITION BY a.ts_code ORDER BY a.trade_date
                    ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                ) AS amount60
            FROM daily_adj_cache a
            JOIN daily d ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date
            LEFT JOIN stock_st st ON a.ts_code = st.ts_code AND a.trade_date = st.trade_date
            WHERE a.trade_date >= '{lookback}'
        ),
        returns AS (
            SELECT
                *,
                close / NULLIF(prev_close, 0) - 1 AS ret,
                close / NULLIF(close_20, 0) - 1 AS ret20,
                close / NULLIF(close_120, 0) - 1 AS ret120
            FROM bars
        )
        SELECT
            *,
            STDDEV_SAMP(ret) OVER(
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
            ) AS vol60,
            STDDEV_SAMP(CASE WHEN ret < 0 THEN ret END) OVER(
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
            ) AS downside_vol60,
            MIN(ret) OVER(
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
            ) AS worst_ret60,
            QUANTILE_CONT(amount, 0.2) OVER(PARTITION BY trade_date) AS amount_p20,
            CASE
              WHEN pre_close IS NULL OR pre_close <= 0 THEN false
              WHEN st_name IS NOT NULL THEN open >= pre_close * 1.047
              ELSE open >= pre_close * 1.097
            END AS limit_up,
            CASE
              WHEN pre_close IS NULL OR pre_close <= 0 THEN false
              WHEN st_name IS NOT NULL THEN open <= pre_close * 0.953
              ELSE open <= pre_close * 0.903
            END AS limit_down,
            COALESCE(volume, 0) <= 0 OR COALESCE(amount, 0) <= 0 AS is_suspended
        FROM returns
        WHERE trade_date >= '{start}'
          AND open > 0 AND close > 0
        """
    )


def load_month_end_signal_dates(connection: DuckDBConnection) -> list[str]:
    """返回每月最后一个交易日，并剔除没有后续交易日的末尾月份。"""
    rows = connection.execute(
        """
        SELECT MAX(trade_date) AS signal_date
        FROM features
        GROUP BY SUBSTR(trade_date, 1, 6)
        HAVING MAX(trade_date) < (SELECT MAX(trade_date) FROM features)
        ORDER BY signal_date
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def load_feature_bars(
    connection: DuckDBConnection,
    symbols: list[str] | None = None,
) -> pd.DataFrame:
    """读取统一 schema 的研究日线面板。"""
    where = ""
    parameters: list[str] = []
    if symbols is not None:
        if not symbols:
            return _empty_bars()
        placeholders = ",".join("?" for _ in symbols)
        where = f"WHERE symbol IN ({placeholders})"
        parameters = [str(symbol) for symbol in symbols]
    frame = connection.execute(
        f"""
        SELECT trade_date, symbol, open, high, low, close, volume, amount,
               is_suspended, limit_up, limit_down
        FROM features
        {where}
        ORDER BY trade_date, symbol
        """,
        parameters,
    ).fetchdf()
    if frame.empty:
        return _empty_bars()
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    return frame.set_index(["date", "symbol"]).sort_index()


def load_trading_calendar(connection: DuckDBConnection) -> list[pd.Timestamp]:
    """从行情特征表读取真实交易日历。"""
    dates = connection.execute(
        "SELECT DISTINCT trade_date FROM features ORDER BY trade_date"
    ).fetchdf()["trade_date"]
    return list(pd.to_datetime(dates, format="%Y%m%d"))


def load_open_prices_on_dates(
    connection: DuckDBConnection,
    trade_dates: list[str],
) -> pd.DataFrame:
    """仅读取标签计算需要的日期和开盘价，避免加载全量日线面板。"""
    normalized = sorted({_normalize_date(value) for value in trade_dates})
    if not normalized:
        return pd.DataFrame(columns=["trade_date", "symbol", "open"])
    placeholders = ",".join("?" for _ in normalized)
    return connection.execute(
        f"""
        SELECT trade_date, symbol, open
        FROM features
        WHERE trade_date IN ({placeholders})
        ORDER BY trade_date, symbol
        """,
        normalized,
    ).fetchdf()


def _empty_bars() -> pd.DataFrame:
    columns = [
        "trade_date", "open", "high", "low", "close", "volume", "amount",
        "is_suspended", "limit_up", "limit_down",
    ]
    index = pd.MultiIndex.from_arrays([[], []], names=["date", "symbol"])
    return pd.DataFrame(columns=columns, index=index)


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
