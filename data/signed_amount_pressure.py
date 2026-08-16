"""成交额加权涨跌压力的历史窗口数据门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


SIGNED_AMOUNT_PRESSURE_TABLE = "signed_amount_pressure_features"


class DuckDBConnection(Protocol):
    """声明成交额压力物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_signed_amount_pressure(
    connection: DuckDBConnection,
    *,
    window: int = 20,
    lookback_start: str = "20141101",
    research_start: str = "20150101",
) -> str:
    """物化成交额加权的日收益方向压力。

    该值仅是日线量价代理，并非真实主动买卖盘。上涨日成交额记正、下跌日
    成交额记负、平盘记零，再除以窗口总成交额，理论范围为 ``[-1, 1]``。
    """
    if window < 2:
        raise ValueError("成交额压力窗口必须至少包含2个观测")
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    preceding = window - 1
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {SIGNED_AMOUNT_PRESSURE_TABLE} AS
        WITH bars AS (
            SELECT
                a.ts_code AS symbol,
                a.trade_date,
                CAST(a.close_qfq AS DOUBLE) AS close,
                CAST(d.amount AS DOUBLE) AS amount,
                LAG(a.close_qfq) OVER(
                    PARTITION BY a.ts_code ORDER BY a.trade_date
                ) AS previous_close,
                LAG(a.close_qfq, {window}) OVER(
                    PARTITION BY a.ts_code ORDER BY a.trade_date
                ) AS close_window_start
            FROM daily_adj_cache a
            JOIN daily d
              ON a.ts_code = d.ts_code
             AND a.trade_date = d.trade_date
            WHERE a.trade_date >= '{lookback}'
              AND a.close_qfq > 0
              AND d.amount > 0
        ),
        daily_pressure AS (
            SELECT
                *,
                close / NULLIF(previous_close, 0) - 1 AS daily_return,
                CASE
                    WHEN close > previous_close THEN amount
                    WHEN close < previous_close THEN -amount
                    ELSE 0.0
                END AS signed_amount
            FROM bars
            WHERE previous_close > 0
        ),
        windows AS (
            SELECT
                *,
                SUM(signed_amount) OVER window_spec AS signed_amount_sum,
                SUM(amount) OVER window_spec AS amount_sum,
                MAX(amount) OVER window_spec AS maximum_daily_amount,
                SUM(CASE WHEN daily_return > 0 THEN amount ELSE 0 END)
                    OVER window_spec AS positive_amount_sum,
                SUM(CASE WHEN daily_return < 0 THEN amount ELSE 0 END)
                    OVER window_spec AS negative_amount_sum,
                SUM(CASE WHEN daily_return = 0 THEN amount ELSE 0 END)
                    OVER window_spec AS neutral_amount_sum,
                SUM(CASE WHEN daily_return > 0 THEN 1 ELSE 0 END)
                    OVER window_spec AS positive_days,
                COUNT(*) OVER window_spec AS observations
            FROM daily_pressure
            WINDOW window_spec AS (
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
            )
        )
        SELECT
            symbol,
            trade_date,
            close / NULLIF(close_window_start, 0) - 1 AS return_20d,
            signed_amount_sum / NULLIF(amount_sum, 0)
                AS signed_amount_pressure,
            positive_amount_sum / NULLIF(amount_sum, 0)
                AS positive_amount_share,
            negative_amount_sum / NULLIF(amount_sum, 0)
                AS negative_amount_share,
            neutral_amount_sum / NULLIF(amount_sum, 0)
                AS neutral_amount_share,
            positive_days::DOUBLE / observations AS positive_day_share,
            maximum_daily_amount / NULLIF(amount_sum, 0)
                AS maximum_daily_amount_share,
            amount_sum,
            observations
        FROM windows
        WHERE trade_date >= '{start}'
          AND observations = {window}
          AND close_window_start > 0
          AND amount_sum > 0
        """
    )
    return SIGNED_AMOUNT_PRESSURE_TABLE


def load_signed_amount_pressure_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经物化的成交额压力面板。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {SIGNED_AMOUNT_PRESSURE_TABLE}
        ORDER BY trade_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
