"""隔夜跳空风险研究使用的点时行情特征。"""

from __future__ import annotations

from typing import Any


OVERNIGHT_GAP_RISK_TABLE = "overnight_gap_risk_features"


def materialize_overnight_gap_risk(
    connection: Any,
    *,
    window: int = 60,
    minimum_observations: int = 50,
) -> None:
    """仅用当日及历史开盘相对前收的对数收益计算波动。"""
    if window < 2:
        raise ValueError("window must be at least 2")
    if minimum_observations < 2 or minimum_observations > window:
        raise ValueError("minimum_observations must be within window")
    preceding = window - 1
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {OVERNIGHT_GAP_RISK_TABLE} AS
        WITH gaps AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                CASE
                  WHEN open_qfq > 0 AND pre_close_qfq > 0
                  THEN LN(open_qfq / pre_close_qfq)
                END AS overnight_return
            FROM daily_adj_cache
        ),
        rolling AS (
            SELECT
                symbol,
                trade_date,
                STDDEV_SAMP(overnight_return) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                ) AS overnight_volatility,
                COUNT(overnight_return) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                ) AS overnight_observations
            FROM gaps
        )
        SELECT
            trade_date,
            symbol,
            overnight_volatility,
            overnight_observations
        FROM rolling
        WHERE overnight_observations >= {minimum_observations}
          AND overnight_volatility IS NOT NULL
          AND overnight_volatility >= 0
        """
    )
