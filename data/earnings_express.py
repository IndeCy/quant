"""业绩快报利润增长加速度的公告日 as-of 门面。

本地源表的 ``yoy_net_profit`` 实际存储上年净利润金额。该语义已通过
正式财报交叉校验，本模块显式改名后自行计算同比，禁止因子沿用错误列名。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


EARNINGS_ACCELERATION_ASOF_TABLE = "earnings_acceleration_asof"


class DuckDBConnection(Protocol):
    """声明快报事件门面所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class EarningsExpressPaths:
    """业绩快报数据文件位置。"""

    express: Path

    def validate(self) -> None:
        """检查文件存在，避免创建空数据库。"""
        if not self.express.exists():
            raise FileNotFoundError(f"缺少业绩快报 DuckDB: {self.express.resolve()}")


def attach_earnings_express_database(
    connection: DuckDBConnection,
    paths: EarningsExpressPaths,
) -> None:
    """以只读方式挂载业绩快报数据库。"""
    paths.validate()
    escaped = str(paths.express.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS express_db (READ_ONLY)"
    )


def create_earnings_express_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """创建月度信号日临时表。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE express_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO express_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_earnings_acceleration_asof(
    connection: DuckDBConnection,
) -> str:
    """物化最新可见年度快报及上一年度增长率。

    最新快报财年距信号年只能为1至2年，兼容年报快报通常在次年披露，
    同时防止多年未发布快报的陈旧信号永久有效。
    """
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {EARNINGS_ACCELERATION_ASOF_TABLE} AS
        WITH annual AS (
            SELECT
                ts_code AS symbol,
                CAST(LEFT(end_date, 4) AS INTEGER) AS fiscal_year,
                ann_date AS publish_date,
                CAST(n_income AS DOUBLE) AS current_net_income,
                CAST(yoy_net_profit AS DOUBLE) AS prior_year_net_income,
                CASE
                    WHEN CAST(n_income AS DOUBLE) > 0
                     AND CAST(yoy_net_profit AS DOUBLE) > 0
                    THEN CAST(n_income AS DOUBLE)
                         / CAST(yoy_net_profit AS DOUBLE) - 1.0
                END AS profit_growth
            FROM express_db.default_table
            WHERE RIGHT(end_date, 4) = '1231'
              AND ann_date IS NOT NULL
        ),
        paired AS (
            SELECT
                c.symbol,
                c.fiscal_year,
                c.publish_date,
                c.current_net_income,
                c.prior_year_net_income,
                c.profit_growth,
                p.publish_date AS prior_publish_date,
                p.profit_growth AS prior_profit_growth,
                c.profit_growth - p.profit_growth AS profit_acceleration
            FROM annual c
            JOIN annual p
              ON c.symbol = p.symbol AND c.fiscal_year = p.fiscal_year + 1
            WHERE c.profit_growth IS NOT NULL
              AND p.profit_growth IS NOT NULL
        ),
        ranked AS (
            SELECT
                d.signal_date,
                p.*,
                CAST(LEFT(d.signal_date, 4) AS INTEGER) - p.fiscal_year
                    AS fiscal_year_age,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, p.symbol
                    ORDER BY p.fiscal_year DESC, p.publish_date DESC
                ) AS rn
            FROM express_signal_dates d
            JOIN paired p
              ON p.publish_date <= d.signal_date
             AND p.prior_publish_date <= d.signal_date
            WHERE CAST(LEFT(d.signal_date, 4) AS INTEGER) - p.fiscal_year
                  BETWEEN 1 AND 2
        )
        SELECT
            signal_date,
            symbol,
            fiscal_year,
            fiscal_year_age,
            publish_date,
            prior_publish_date,
            current_net_income,
            prior_year_net_income,
            profit_growth,
            prior_profit_growth,
            profit_acceleration
        FROM ranked
        WHERE rn = 1
        """
    )
    return EARNINGS_ACCELERATION_ASOF_TABLE


def load_earnings_acceleration_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经通过公告日和时效约束的快报截面。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            symbol,
            fiscal_year,
            fiscal_year_age,
            publish_date,
            prior_publish_date,
            current_net_income,
            prior_year_net_income,
            profit_growth,
            prior_profit_growth,
            profit_acceleration
        FROM {EARNINGS_ACCELERATION_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    """校验并标准化交易日。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
