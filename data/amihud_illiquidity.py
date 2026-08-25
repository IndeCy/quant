"""Amihud 非流动性因子的统一日线门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


AMIHUD_ILLIQUIDITY_TABLE = "amihud_illiquidity_features"


class DuckDBConnection(Protocol):
    """声明非流动性物化所需的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_amihud_illiquidity(
    connection: DuckDBConnection,
    *,
    window: int = 60,
    lookback_start: str = "20140901",
    research_start: str = "20150101",
) -> str:
    """使用前复权收益和人民币成交额构造滚动 Amihud 指标。"""
    if window <= 1:
        raise ValueError("window must be greater than one")
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {AMIHUD_ILLIQUIDITY_TABLE} AS
        WITH bars AS (
            SELECT
                a.ts_code AS symbol,
                a.trade_date,
                a.close_qfq AS close,
                LAG(a.close_qfq) OVER(
                    PARTITION BY a.ts_code ORDER BY a.trade_date
                ) AS previous_close,
                LAG(a.close_qfq, {window}) OVER(
                    PARTITION BY a.ts_code ORDER BY a.trade_date
                ) AS close_window_start,
                d.amount * 1000.0 AS amount_rmb
            FROM daily_adj_cache a
            JOIN daily d
              ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date
            WHERE a.trade_date >= '{lookback}'
        ),
        daily_impact AS (
            SELECT
                symbol,
                trade_date,
                close,
                close_window_start,
                amount_rmb,
                ABS(close / NULLIF(previous_close, 0) - 1)
                    / NULLIF(amount_rmb, 0) AS impact
            FROM bars
            WHERE close > 0
              AND previous_close > 0
              AND amount_rmb > 0
        ),
        windows AS (
            SELECT
                symbol,
                trade_date,
                close_window_start,
                close / NULLIF(close_window_start, 0) - 1 AS return_60d,
                AVG(impact) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS amihud_illiquidity,
                AVG(amount_rmb) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS average_amount_rmb,
                MIN(amount_rmb) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS minimum_amount_rmb,
                MAX(impact) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS maximum_daily_impact,
                SUM(impact) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS total_impact,
                COUNT(*) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS observations
            FROM daily_impact
        )
        SELECT
            symbol,
            trade_date,
            return_60d,
            amihud_illiquidity,
            average_amount_rmb,
            minimum_amount_rmb,
            maximum_daily_impact / NULLIF(total_impact, 0)
                AS maximum_daily_impact_share,
            observations
        FROM windows
        WHERE trade_date >= '{start}'
          AND observations = {window}
          AND close_window_start > 0
          AND amihud_illiquidity > 0
        """
    )
    return AMIHUD_ILLIQUIDITY_TABLE


def load_amihud_illiquidity_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化的 Amihud 非流动性面板。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {AMIHUD_ILLIQUIDITY_TABLE}
        ORDER BY trade_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
