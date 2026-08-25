"""融资净买入强度的 T-1 点时数据门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from data.margin_trades import MARGIN_DETAIL_TABLE


MARGIN_FLOW_ASOF_TABLE = "margin_flow_asof"


class DuckDBConnection(Protocol):
    """声明融资流点时物化需要的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


def create_margin_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE margin_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO margin_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_margin_flow_asof(
    connection: DuckDBConnection,
    *,
    lookback_trading_days: int = 20,
) -> str:
    """物化信号日前一交易日可见的连续融资流强度。

    两融明细在下一交易日早间披露，因此 T 日收盘信号只允许使用 T-1 及
    以前记录。``rank_span`` 强制窗口覆盖连续真实交易日，避免停留在两融
    名单外的旧记录被当成最近 20 日。
    """
    if lookback_trading_days <= 1:
        raise ValueError("lookback_trading_days must be greater than one")
    prior_rows = lookback_trading_days - 1
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {MARGIN_FLOW_ASOF_TABLE} AS
        WITH calendar AS (
            SELECT
                trade_date,
                ROW_NUMBER() OVER(ORDER BY trade_date) AS trade_rank
            FROM (SELECT DISTINCT trade_date FROM features)
        ),
        margin_bars AS (
            SELECT
                m.trade_date,
                m.ts_code AS symbol,
                c.trade_rank,
                CAST(m.rzmre AS DOUBLE) - CAST(m.rzche AS DOUBLE) AS net_buy,
                f.amount * 1000.0 AS turnover_amount
            FROM margin_db.{MARGIN_DETAIL_TABLE} m
            JOIN features f
              ON m.trade_date = f.trade_date AND m.ts_code = f.symbol
            JOIN calendar c ON m.trade_date = c.trade_date
        ),
        rolling AS (
            SELECT
                *,
                SUM(net_buy) OVER window_spec AS net_buy_20d,
                SUM(turnover_amount) OVER window_spec AS turnover_20d,
                trade_rank - LAG(trade_rank, {prior_rows})
                    OVER(PARTITION BY symbol ORDER BY trade_date)
                    AS rank_span
            FROM margin_bars
            WINDOW window_spec AS (
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN {prior_rows} PRECEDING AND CURRENT ROW
            )
        ),
        signal_previous AS (
            SELECT
                s.signal_date,
                MAX(c.trade_date) AS visible_through_date
            FROM margin_signal_dates s
            JOIN calendar c ON c.trade_date < s.signal_date
            GROUP BY s.signal_date
        )
        SELECT
            s.signal_date,
            s.visible_through_date,
            r.symbol,
            r.net_buy_20d,
            r.turnover_20d,
            r.net_buy_20d / NULLIF(r.turnover_20d, 0)
                AS margin_flow_intensity
        FROM signal_previous s
        JOIN rolling r ON r.trade_date = s.visible_through_date
        JOIN features f
          ON f.trade_date = s.signal_date AND f.symbol = r.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        WHERE r.rank_span = {prior_rows}
          AND r.turnover_20d > 0
          AND f.st_name IS NULL
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
        """
    )
    return MARGIN_FLOW_ASOF_TABLE


def load_margin_flow_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经通过 T-1 和连续交易日约束的融资流截面。"""
    return connection.execute(
        f"""
        SELECT signal_date, visible_through_date, symbol,
               net_buy_20d, turnover_20d, margin_flow_intensity
        FROM {MARGIN_FLOW_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
