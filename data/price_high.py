"""前复权价格相对 52 周最高收盘的研究特征。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


PRICE_HIGH_TABLE = "price_high_proximity"
PRICE_BREAKOUT_TABLE = "price_high_breakout"


class DuckDBConnection(Protocol):
    """声明价格高点特征所需的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_price_high_proximity(
    connection: DuckDBConnection,
    *,
    window: int = 252,
    lookback_start: str = "20130101",
    research_start: str = "20150101",
) -> str:
    """仅用信号日及之前的 qfq 收盘价计算 52 周高点接近度。"""
    if window <= 1:
        raise ValueError("window must be greater than one")
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {PRICE_HIGH_TABLE} AS
        WITH rolling_high AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                close_qfq AS close,
                MAX(close_qfq) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS max_close,
                COUNT(close_qfq) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS observations
            FROM daily_adj_cache
            WHERE trade_date >= '{lookback}'
              AND close_qfq > 0
        )
        SELECT
            symbol,
            trade_date,
            close,
            max_close,
            close / NULLIF(max_close, 0) AS high_proximity,
            observations
        FROM rolling_high
        WHERE trade_date >= '{start}'
          AND observations = {window}
        """
    )
    return PRICE_HIGH_TABLE


def load_price_high_snapshot(connection: DuckDBConnection) -> pd.DataFrame:
    """读取已经物化的高点接近度面板。"""
    return connection.execute(
        f"SELECT * FROM {PRICE_HIGH_TABLE} ORDER BY trade_date, symbol"
    ).fetchdf()


def materialize_price_high_breakout(
    connection: DuckDBConnection,
    *,
    window: int = 252,
    lookback_start: str = "20130101",
    research_start: str = "20150101",
) -> str:
    """用前 252 日最高收盘计算突破强度，避免当日新高大面积并列。"""
    if window <= 1:
        raise ValueError("window must be greater than one")
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {PRICE_BREAKOUT_TABLE} AS
        WITH prior_high AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                close_qfq AS close,
                MAX(close_qfq) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                    ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING
                ) AS prior_max_close,
                COUNT(close_qfq) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                    ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING
                ) AS observations
            FROM daily_adj_cache
            WHERE trade_date >= '{lookback}'
              AND close_qfq > 0
        )
        SELECT
            symbol,
            trade_date,
            close,
            prior_max_close,
            close / NULLIF(prior_max_close, 0) AS breakout_strength,
            observations
        FROM prior_high
        WHERE trade_date >= '{start}'
          AND observations = {window}
        """
    )
    return PRICE_BREAKOUT_TABLE


def load_price_breakout_snapshot(connection: DuckDBConnection) -> pd.DataFrame:
    """读取前高突破强度面板。"""
    return connection.execute(
        f"SELECT * FROM {PRICE_BREAKOUT_TABLE} ORDER BY trade_date, symbol"
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
