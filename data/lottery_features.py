"""彩票偏好行为因子的日线特征门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


LOTTERY_MAX_TABLE = "lottery_max_features"


class DuckDBConnection(Protocol):
    """声明行为特征门面需要的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_lottery_max_features(
    connection: DuckDBConnection,
    *,
    window: int = 20,
) -> str:
    """计算过去固定交易日窗口内的最大单日收益。"""
    if window < 2 or window > 252:
        raise ValueError("window must be between 2 and 252")
    preceding = window - 1
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {LOTTERY_MAX_TABLE} AS
        WITH rolling AS (
            SELECT
                trade_date,
                symbol,
                MAX(ret) OVER(
                    PARTITION BY symbol
                    ORDER BY trade_date
                    ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                ) AS max_ret{window},
                COUNT(ret) OVER(
                    PARTITION BY symbol
                    ORDER BY trade_date
                    ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                ) AS observations
            FROM features
        )
        SELECT trade_date, symbol, max_ret{window}, observations
        FROM rolling
        WHERE observations = {window}
        """
    )
    return LOTTERY_MAX_TABLE


def load_lottery_max_snapshot(
    connection: DuckDBConnection,
    *,
    window: int = 20,
) -> pd.DataFrame:
    """读取已经物化的低 MAX 特征。"""
    if window < 2 or window > 252:
        raise ValueError("window must be between 2 and 252")
    return connection.execute(
        f"""
        SELECT trade_date, symbol, max_ret{window}, observations
        FROM {LOTTERY_MAX_TABLE}
        ORDER BY trade_date, symbol
        """
    ).fetchdf()
