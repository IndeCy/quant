"""公募基金产品级持仓广度 as-of 门面。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


FUND_OWNERSHIP_ASOF_TABLE = "fund_ownership_breadth_asof"
class DuckDBConnection(Protocol):
    """声明点时门面使用的最小 DuckDB 能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""

def attach_fund_ownership_database(
    connection: DuckDBConnection,
    database_path: Path,
) -> None:
    """以只读方式挂载基金持仓缓存。"""
    if not database_path.exists():
        raise FileNotFoundError(f"缺少基金持仓缓存: {database_path.resolve()}")
    escaped = str(database_path.resolve()).replace("'", "''")
    connection.execute(f"ATTACH DATABASE '{escaped}' AS fund_ownership_db (READ_ONLY)")


def create_fund_ownership_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日临时表。"""
    normalized = [_normalize_date(item) for item in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE fund_ownership_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO fund_ownership_signal_dates VALUES (?)",
            [(item,) for item in normalized],
        )


def materialize_fund_ownership_breadth_asof(
    connection: DuckDBConnection,
) -> str:
    """按固定披露截止日选最近两期，计算产品持有占比变化。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {FUND_OWNERSHIP_ASOF_TABLE} AS
        WITH available_periods AS (
            SELECT
                d.signal_date,
                p.end_date,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date ORDER BY p.end_date DESC
                ) AS period_rank
            FROM fund_ownership_signal_dates d
            JOIN (
                SELECT DISTINCT end_date, available_date
                FROM fund_ownership_db.fund_product_top10
            ) p ON p.available_date <= d.signal_date
        ),
        selected_periods AS (
            SELECT * FROM available_periods WHERE period_rank <= 2
        ),
        visible_holdings AS (
            SELECT
                p.signal_date,
                p.period_rank,
                p.end_date,
                h.product_key,
                h.symbol,
                h.ann_date
            FROM selected_periods p
            JOIN fund_ownership_db.fund_product_top10 h
              ON p.end_date = h.end_date
             AND h.ann_date <= p.signal_date
        ),
        period_totals AS (
            SELECT
                signal_date,
                period_rank,
                end_date,
                COUNT(DISTINCT product_key) AS total_products
            FROM visible_holdings
            GROUP BY signal_date, period_rank, end_date
        ),
        breadth AS (
            SELECT
                h.signal_date,
                h.period_rank,
                h.end_date,
                h.symbol,
                COUNT(DISTINCT h.product_key) AS product_holders,
                MAX(h.ann_date) AS latest_ann_date,
                MAX(t.total_products) AS total_products,
                COUNT(DISTINCT h.product_key)::DOUBLE
                    / NULLIF(MAX(t.total_products), 0) AS breadth_share
            FROM visible_holdings h
            JOIN period_totals t
              ON h.signal_date = t.signal_date
             AND h.period_rank = t.period_rank
             AND h.end_date = t.end_date
            GROUP BY h.signal_date, h.period_rank, h.end_date, h.symbol
        ),
        paired AS (
            SELECT
                COALESCE(c.signal_date, p.signal_date) AS signal_date,
                COALESCE(c.symbol, p.symbol) AS symbol,
                c.end_date AS current_period,
                p.end_date AS prior_period,
                c.latest_ann_date,
                COALESCE(c.product_holders, 0) AS current_product_holders,
                COALESCE(p.product_holders, 0) AS prior_product_holders,
                COALESCE(c.total_products, 0) AS current_total_products,
                COALESCE(p.total_products, 0) AS prior_total_products,
                COALESCE(c.breadth_share, 0.0) AS current_breadth_share,
                COALESCE(p.breadth_share, 0.0) AS prior_breadth_share
            FROM (SELECT * FROM breadth WHERE period_rank = 1) c
            FULL OUTER JOIN (SELECT * FROM breadth WHERE period_rank = 2) p
              ON c.signal_date = p.signal_date AND c.symbol = p.symbol
        )
        SELECT
            *,
            current_breadth_share - prior_breadth_share AS breadth_change
        FROM paired
        WHERE current_period IS NOT NULL AND prior_period IS NOT NULL
        """
    )
    return FUND_OWNERSHIP_ASOF_TABLE


def load_fund_ownership_snapshot(connection: DuckDBConnection) -> pd.DataFrame:
    """读取已物化的点时基金持仓广度截面。"""
    return connection.execute(
        f"SELECT * FROM {FUND_OWNERSHIP_ASOF_TABLE} "
        "ORDER BY signal_date, symbol"
    ).fetchdf()
def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    datetime.strptime(normalized, "%Y%m%d")
    return normalized
