"""长期反转研究使用的点时价格特征。"""

from __future__ import annotations

from typing import Any


LONG_TERM_REVERSAL_TABLE = "long_term_reversal_features"


def materialize_long_term_reversal(
    connection: Any,
    *,
    long_lag: int = 756,
    recent_lag: int = 252,
    source_start: str = "20110101",
    research_start: str = "20150101",
) -> None:
    """用信号日前的两个滞后价格计算 36 至 13 个月累计收益。"""
    if long_lag <= recent_lag or recent_lag <= 0:
        raise ValueError("long_lag must be greater than recent_lag")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {LONG_TERM_REVERSAL_TABLE} AS
        WITH ordered AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                close_qfq,
                LAG(close_qfq, {recent_lag}) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS close_recent_lag,
                LAG(close_qfq, {long_lag}) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS close_long_lag
            FROM daily_adj_cache
            WHERE trade_date >= ?
        )
        SELECT
            trade_date,
            symbol,
            close_recent_lag,
            close_long_lag,
            close_recent_lag / NULLIF(close_long_lag, 0) - 1
                AS long_term_return
        FROM ordered
        WHERE trade_date >= ?
          AND close_recent_lag > 0
          AND close_long_lag > 0
        """,
        [source_start, research_start],
    )
