"""个股自身异常成交额的历史窗口数据门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


ABNORMAL_AMOUNT_TABLE = "abnormal_amount_features"


class DuckDBConnection(Protocol):
    """声明异常成交额物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_abnormal_amount(
    connection: DuckDBConnection,
    *,
    recent_window: int = 20,
    baseline_window: int = 60,
    lookback_start: str = "20140901",
    research_start: str = "20150101",
) -> str:
    """物化近期成交额相对此前基线的异常活跃度。

    当前日及此前19个观测构成近期20日；再之前60个观测构成独立基线，
    两段窗口不重叠。成交额只在个股自身时间序列内比较，不冒充换手率。
    """
    if recent_window < 2 or baseline_window < 2:
        raise ValueError("成交额窗口必须至少包含2个观测")
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    recent_start = recent_window - 1
    baseline_end = recent_window
    baseline_start = recent_window + baseline_window - 1
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {ABNORMAL_AMOUNT_TABLE} AS
        WITH bars AS (
            SELECT
                a.ts_code AS symbol,
                a.trade_date,
                CAST(a.close_qfq AS DOUBLE) AS close,
                CAST(d.amount AS DOUBLE) AS amount
            FROM daily_adj_cache a
            JOIN daily d
              ON a.ts_code = d.ts_code
             AND a.trade_date = d.trade_date
            WHERE a.trade_date >= '{lookback}'
              AND a.close_qfq > 0
              AND d.amount > 0
        ),
        windows AS (
            SELECT
                *,
                LAG(close, {recent_window}) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                ) AS close_recent_start,
                AVG(amount) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {recent_start} PRECEDING AND CURRENT ROW
                ) AS recent_amount_average,
                COUNT(amount) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {recent_start} PRECEDING AND CURRENT ROW
                ) AS recent_observations,
                AVG(amount) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {baseline_start} PRECEDING
                             AND {baseline_end} PRECEDING
                ) AS baseline_amount_average,
                COUNT(amount) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {baseline_start} PRECEDING
                             AND {baseline_end} PRECEDING
                ) AS baseline_observations
            FROM bars
        )
        SELECT
            symbol,
            trade_date,
            close / NULLIF(close_recent_start, 0) - 1 AS return_20d,
            recent_amount_average,
            baseline_amount_average,
            recent_amount_average / NULLIF(baseline_amount_average, 0)
                AS abnormal_amount_ratio,
            LN(
                recent_amount_average / NULLIF(baseline_amount_average, 0)
            ) AS log_abnormal_amount,
            recent_observations,
            baseline_observations
        FROM windows
        WHERE trade_date >= '{start}'
          AND recent_observations = {recent_window}
          AND baseline_observations = {baseline_window}
          AND close_recent_start > 0
          AND recent_amount_average > 0
          AND baseline_amount_average > 0
        """
    )
    return ABNORMAL_AMOUNT_TABLE


def load_abnormal_amount_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经物化的异常成交额面板。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {ABNORMAL_AMOUNT_TABLE}
        ORDER BY trade_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
