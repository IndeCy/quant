"""前复权日收益的隔夜与日内分解特征。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


INTRADAY_STRENGTH_TABLE = "intraday_strength"


class DuckDBConnection(Protocol):
    """声明收益分解所需的最小 DuckDB 连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""


def materialize_intraday_strength(
    connection: DuckDBConnection,
    *,
    window: int = 20,
    lookback_start: str = "20141001",
    research_start: str = "20150101",
) -> str:
    """用当日及此前数据计算日内强度减隔夜情绪，不读取未来行情。"""
    if window <= 1:
        raise ValueError("window must be greater than one")
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {INTRADAY_STRENGTH_TABLE} AS
        WITH lagged AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                open_qfq AS open,
                close_qfq AS close,
                LAG(close_qfq) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS prev_close
            FROM daily_adj_cache
            WHERE trade_date >= '{lookback}'
        ),
        components AS (
            SELECT
                symbol,
                trade_date,
                LN(close / open) AS intraday_log_return,
                LN(open / prev_close) AS overnight_log_return
            FROM lagged
            WHERE open > 0 AND close > 0 AND prev_close > 0
        ),
        rolling AS (
            SELECT
                symbol,
                trade_date,
                SUM(intraday_log_return) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS intraday_log_return_20,
                SUM(overnight_log_return) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS overnight_log_return_20,
                COUNT(*) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS observations
            FROM components
        )
        SELECT
            symbol,
            trade_date,
            intraday_log_return_20,
            overnight_log_return_20,
            intraday_log_return_20 - overnight_log_return_20
                AS intraday_strength,
            EXP(intraday_log_return_20 + overnight_log_return_20) - 1
                AS decomposed_total_return,
            observations
        FROM rolling
        WHERE trade_date >= '{start}'
          AND observations = {window}
        """
    )
    return INTRADAY_STRENGTH_TABLE


def load_intraday_strength_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化的收益时段分解面板。"""
    return connection.execute(
        f"SELECT * FROM {INTRADAY_STRENGTH_TABLE} ORDER BY trade_date, symbol"
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
