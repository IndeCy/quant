"""现金分红实施事件的除息日 as-of 数据门面。

本模块把标准分红表转换成信号日可见的年度现金分配序列。因子层不能直接
读取原始 DuckDB，也不能使用尚未除息的预案或股东大会方案。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


DIVIDEND_GROWTH_ASOF_TABLE = "dividend_growth_asof"


class DuckDBConnection(Protocol):
    """声明股息事件门面所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class DividendEventPaths:
    """标准分红数据文件位置。"""

    dividend: Path

    def validate(self) -> None:
        """检查文件存在，避免 DuckDB 自动创建空库。"""
        if not self.dividend.exists():
            raise FileNotFoundError(f"缺少标准分红 DuckDB: {self.dividend.resolve()}")


def attach_dividend_database(
    connection: DuckDBConnection,
    paths: DividendEventPaths,
) -> None:
    """以只读方式挂载标准分红数据库。"""
    paths.validate()
    escaped = str(paths.dividend.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS dividend_db (READ_ONLY)"
    )


def create_dividend_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """创建月度信号日临时表。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE dividend_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO dividend_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_dividend_growth_asof(connection: DuckDBConnection) -> str:
    """物化信号日可见的最近三个年度现金分红总额。

    现金总额使用 ``cash_div_tax * base_share``。两者的单位不会影响同一公司
    跨年度增长率。只使用 ``div_proc='实施'`` 且 ``ex_date <= signal_date``；
    同一年度存在多次真实派息时按年度求和。
    """
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {DIVIDEND_GROWTH_ASOF_TABLE} AS
        WITH implemented AS (
            SELECT
                ts_code AS symbol,
                CAST(LEFT(end_date, 4) AS INTEGER) AS fiscal_year,
                ex_date,
                CAST(cash_div_tax AS DOUBLE) * CAST(base_share AS DOUBLE)
                    AS cash_payout
            FROM dividend_db.dividend
            WHERE div_proc = '实施'
              AND RIGHT(end_date, 4) = '1231'
              AND ex_date IS NOT NULL
              AND CAST(cash_div_tax AS DOUBLE) > 0
              AND CAST(base_share AS DOUBLE) > 0
        ),
        annual_visible AS (
            SELECT
                d.signal_date,
                i.symbol,
                i.fiscal_year,
                SUM(i.cash_payout) AS annual_cash_payout,
                MAX(i.ex_date) AS latest_ex_date
            FROM dividend_signal_dates d
            JOIN implemented i ON i.ex_date <= d.signal_date
            GROUP BY d.signal_date, i.symbol, i.fiscal_year
        ),
        latest_year AS (
            SELECT
                signal_date,
                symbol,
                MAX(fiscal_year) AS latest_fiscal_year
            FROM annual_visible
            GROUP BY signal_date, symbol
        )
        SELECT
            y.signal_date,
            y.symbol,
            y.latest_fiscal_year,
            MAX(a.latest_ex_date) FILTER(
                WHERE a.fiscal_year = y.latest_fiscal_year
            ) AS latest_ex_date,
            MAX(a.annual_cash_payout) FILTER(
                WHERE a.fiscal_year = y.latest_fiscal_year
            ) AS cash_payout_y0,
            MAX(a.annual_cash_payout) FILTER(
                WHERE a.fiscal_year = y.latest_fiscal_year - 1
            ) AS cash_payout_y1,
            MAX(a.annual_cash_payout) FILTER(
                WHERE a.fiscal_year = y.latest_fiscal_year - 2
            ) AS cash_payout_y2
        FROM latest_year y
        JOIN annual_visible a
          ON a.signal_date = y.signal_date AND a.symbol = y.symbol
        GROUP BY y.signal_date, y.symbol, y.latest_fiscal_year
        """
    )
    return DIVIDEND_GROWTH_ASOF_TABLE


def load_dividend_growth_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经通过除息日约束的三年现金分红截面。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            symbol,
            latest_fiscal_year,
            latest_ex_date,
            cash_payout_y0,
            cash_payout_y1,
            cash_payout_y2
        FROM {DIVIDEND_GROWTH_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    """校验并标准化交易日。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
