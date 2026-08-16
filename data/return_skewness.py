"""滚动日收益偏度特征门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


RETURN_SKEWNESS_TABLE = "return_skewness_features"


class DuckDBConnection(Protocol):
    """声明偏度物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_return_skewness_features(
    connection: DuckDBConnection,
    *,
    window: int = 60,
) -> str:
    """计算截至当日收盘的固定窗口样本偏度。"""
    if window < 20 or window > 252:
        raise ValueError("window must be between 20 and 252")
    preceding = window - 1
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {RETURN_SKEWNESS_TABLE} AS
        WITH rolling AS (
            SELECT
                trade_date,
                symbol,
                SKEWNESS(ret) OVER(
                    PARTITION BY symbol
                    ORDER BY trade_date
                    ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                ) AS return_skewness_{window}d,
                COUNT(ret) OVER(
                    PARTITION BY symbol
                    ORDER BY trade_date
                    ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                ) AS observations
            FROM features
        )
        SELECT
            trade_date,
            symbol,
            return_skewness_{window}d,
            observations
        FROM rolling
        WHERE observations = {window}
          AND ISFINITE(return_skewness_{window}d)
        """
    )
    return RETURN_SKEWNESS_TABLE


def load_return_skewness_snapshot(
    connection: DuckDBConnection,
    *,
    window: int = 60,
) -> pd.DataFrame:
    """读取已经物化的滚动偏度截面。"""
    if window < 20 or window > 252:
        raise ValueError("window must be between 20 and 252")
    return connection.execute(
        f"""
        SELECT trade_date, symbol, return_skewness_{window}d, observations
        FROM {RETURN_SKEWNESS_TABLE}
        ORDER BY trade_date, symbol
        """
    ).fetchdf()
