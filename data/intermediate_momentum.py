"""12-1月中期动量研究使用的点时价格特征。"""

from __future__ import annotations

from typing import Any


INTERMEDIATE_MOMENTUM_TABLE = "intermediate_momentum_features"


def materialize_intermediate_momentum(
    connection: Any,
    *,
    formation_lag: int = 252,
    skip_lag: int = 20,
    source_start: str = "20131201",
    research_start: str = "20150101",
) -> None:
    """使用信号日前第252日至第20日的前复权收益。"""
    if formation_lag <= skip_lag or skip_lag <= 0:
        raise ValueError("formation_lag must be greater than skip_lag")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {INTERMEDIATE_MOMENTUM_TABLE} AS
        WITH ordered AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                LAG(close_qfq, {skip_lag}) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS close_skip_lag,
                LAG(close_qfq, {formation_lag}) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS close_formation_lag
            FROM daily_adj_cache
            WHERE trade_date >= ?
        )
        SELECT
            trade_date,
            symbol,
            close_skip_lag,
            close_formation_lag,
            close_skip_lag / NULLIF(close_formation_lag, 0) - 1
                AS intermediate_momentum
        FROM ordered
        WHERE trade_date >= ?
          AND close_skip_lag > 0
          AND close_formation_lag > 0
        """,
        [source_start, research_start],
    )
