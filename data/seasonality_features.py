"""跨年月份季节性因子的点时数据门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


SEASONALITY_TABLE = "monthly_seasonality_features"


class DuckDBConnection(Protocol):
    """声明季节性门面需要的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_monthly_seasonality(
    connection: DuckDBConnection,
    *,
    lookback_years: int = 5,
    min_observations: int = 3,
    research_start: str = "20150101",
) -> str:
    """使用信号日前同一目标月份的历史收益生成季节性评分。"""
    if lookback_years < 1 or lookback_years > 10:
        raise ValueError("lookback_years must be between 1 and 10")
    if min_observations < 1 or min_observations > lookback_years:
        raise ValueError("min_observations must not exceed lookback_years")
    start = _normalize_date(research_start)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {SEASONALITY_TABLE} AS
        WITH monthly_ranked AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                SUBSTR(trade_date, 1, 6) AS month_key,
                CAST(LEFT(trade_date, 4) AS INTEGER) * 12
                    + CAST(SUBSTR(trade_date, 5, 2) AS INTEGER) AS month_index,
                CAST(SUBSTR(trade_date, 5, 2) AS INTEGER) AS calendar_month,
                close_qfq,
                ROW_NUMBER() OVER(
                    PARTITION BY ts_code, SUBSTR(trade_date, 1, 6)
                    ORDER BY trade_date DESC
                ) AS rn
            FROM daily_adj_cache
            WHERE close_qfq > 0
        ),
        monthly_closes AS (
            SELECT
                symbol,
                trade_date AS month_end_date,
                month_key,
                month_index,
                calendar_month,
                close_qfq
            FROM monthly_ranked
            WHERE rn = 1
        ),
        lagged AS (
            SELECT
                *,
                LAG(month_index) OVER(
                    PARTITION BY symbol ORDER BY month_index
                ) AS prior_month_index,
                LAG(close_qfq) OVER(
                    PARTITION BY symbol ORDER BY month_index
                ) AS prior_month_close
            FROM monthly_closes
        ),
        monthly_returns AS (
            SELECT
                symbol,
                month_end_date,
                calendar_month,
                close_qfq / NULLIF(prior_month_close, 0) - 1 AS monthly_return
            FROM lagged
            WHERE month_index - prior_month_index = 1
        ),
        signal_dates AS (
            SELECT
                MAX(trade_date) AS signal_date,
                CASE
                    WHEN CAST(SUBSTR(MAX(trade_date), 5, 2) AS INTEGER) = 12
                    THEN 1
                    ELSE CAST(SUBSTR(MAX(trade_date), 5, 2) AS INTEGER) + 1
                END AS target_month
            FROM features
            GROUP BY SUBSTR(trade_date, 1, 6)
            HAVING MAX(trade_date) < (SELECT MAX(trade_date) FROM features)
               AND MAX(trade_date) >= '{start}'
        ),
        aggregated AS (
            SELECT
                s.signal_date,
                m.symbol,
                s.target_month,
                AVG(m.monthly_return) AS seasonal_mean_return,
                AVG(CASE WHEN m.monthly_return > 0 THEN 1.0 ELSE 0.0 END)
                    AS seasonal_win_rate,
                COUNT(*) AS observations
            FROM signal_dates s
            JOIN monthly_returns m
              ON m.calendar_month = s.target_month
             AND m.month_end_date < s.signal_date
             AND STRPTIME(m.month_end_date, '%Y%m%d')
                 >= STRPTIME(s.signal_date, '%Y%m%d')
                    - INTERVAL {lookback_years} YEAR
            GROUP BY s.signal_date, m.symbol, s.target_month
        )
        SELECT
            signal_date,
            symbol,
            target_month,
            seasonal_mean_return,
            seasonal_win_rate,
            observations
        FROM aggregated
        WHERE observations >= {min_observations}
        """
    )
    return SEASONALITY_TABLE


def load_monthly_seasonality_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取季节性点时截面。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            symbol,
            target_month,
            seasonal_mean_return,
            seasonal_win_rate,
            observations
        FROM {SEASONALITY_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    """只接受 YYYYMMDD 日期。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
