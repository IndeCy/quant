"""交易活跃度稳定性研究使用的点时成交额特征。"""

from __future__ import annotations

from typing import Any


TRADING_ACTIVITY_TABLE = "trading_activity_stability_features"


def materialize_trading_activity_stability(
    connection: Any,
    *,
    window: int = 60,
    minimum_observations: int = 50,
) -> None:
    """仅使用当日及此前成交额计算滚动对数成交额波动。"""
    if window < 2:
        raise ValueError("window must be at least 2")
    if minimum_observations < 2 or minimum_observations > window:
        raise ValueError("minimum_observations must be within window")
    preceding = window - 1
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {TRADING_ACTIVITY_TABLE} AS
        WITH rolling AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                STDDEV_SAMP(
                    CASE WHEN amount > 0 THEN LN(amount) END
                ) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                    ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                ) AS activity_volatility,
                COUNT(
                    CASE WHEN amount > 0 THEN 1 END
                ) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                    ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                ) AS activity_observations
            FROM daily
        )
        SELECT
            trade_date,
            symbol,
            activity_volatility,
            activity_observations
        FROM rolling
        WHERE activity_observations >= {minimum_observations}
          AND activity_volatility IS NOT NULL
          AND activity_volatility >= 0
        """
    )
