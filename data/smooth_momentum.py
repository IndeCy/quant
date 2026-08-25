"""跳过近月的价格路径连续性动量研究特征。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


SMOOTH_MOMENTUM_TABLE = "smooth_momentum"


class DuckDBConnection(Protocol):
    """声明平滑动量物化所需的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_smooth_momentum(
    connection: DuckDBConnection,
    *,
    formation_window: int = 120,
    skip_window: int = 20,
    lookback_start: str = "20140101",
    research_start: str = "20150101",
) -> str:
    """计算中期收益及其上涨日连续性，窗口严格截止到近月之前。"""
    if formation_window <= skip_window + 1:
        raise ValueError("formation_window must exceed skip_window by at least two")
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    path_days = formation_window - skip_window
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {SMOOTH_MOMENTUM_TABLE} AS
        WITH lagged AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                close_qfq AS close,
                LAG(close_qfq) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS prev_close,
                LAG(close_qfq, {skip_window}) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS close_skip,
                LAG(close_qfq, {formation_window}) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS close_formation
            FROM daily_adj_cache
            WHERE trade_date >= '{lookback}'
              AND close_qfq > 0
        ),
        daily_returns AS (
            SELECT
                *,
                close / NULLIF(prev_close, 0) - 1 AS daily_return
            FROM lagged
        ),
        shifted AS (
            SELECT
                *,
                LAG(daily_return, {skip_window}) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                ) AS path_return
            FROM daily_returns
        ),
        path_stats AS (
            SELECT
                symbol,
                trade_date,
                close_skip,
                close_formation,
                COUNT(path_return) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {path_days - 1} PRECEDING AND CURRENT ROW
                ) AS observations,
                SUM(CASE WHEN path_return > 0 THEN 1 ELSE 0 END) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {path_days - 1} PRECEDING AND CURRENT ROW
                ) AS positive_days,
                SUM(CASE WHEN path_return < 0 THEN 1 ELSE 0 END) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {path_days - 1} PRECEDING AND CURRENT ROW
                ) AS negative_days
            FROM shifted
        )
        SELECT
            symbol,
            trade_date,
            close_skip / NULLIF(close_formation, 0) - 1 AS momentum_skip_recent,
            (positive_days - negative_days)::DOUBLE
                / NULLIF(observations, 0) AS path_continuity,
            LN(close_skip / NULLIF(close_formation, 0))
                * (positive_days - negative_days)::DOUBLE
                / NULLIF(observations, 0) AS smooth_momentum,
            positive_days,
            negative_days,
            observations
        FROM path_stats
        WHERE trade_date >= '{start}'
          AND observations = {path_days}
          AND close_skip > 0
          AND close_formation > 0
        """
    )
    return SMOOTH_MOMENTUM_TABLE


def load_smooth_momentum_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化的平滑动量面板。"""
    return connection.execute(
        f"SELECT * FROM {SMOOTH_MOMENTUM_TABLE} ORDER BY trade_date, symbol"
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
