"""年度应计利润因子的 DuckDB as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


ACCRUAL_QUALITY_ASOF_TABLE = "accrual_quality_asof"


class DuckDBConnection(Protocol):
    """声明应计利润门面所需的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class AccrualQualityPaths:
    """应计利润计算所需的三张财务报表。"""

    income: Path
    balance: Path
    cashflow: Path

    def validate(self) -> None:
        """所有源库都存在时才允许挂载，避免部分数据被误用。"""
        missing = [
            str(path.resolve())
            for path in (self.income, self.balance, self.cashflow)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少应计利润财务数据库: {missing}")


def attach_accrual_quality_databases(
    connection: DuckDBConnection,
    paths: AccrualQualityPaths,
) -> None:
    """只读挂载三张财务报表。"""
    paths.validate()
    aliases = {
        "accrual_income_db": paths.income,
        "accrual_balance_db": paths.balance,
        "accrual_cashflow_db": paths.cashflow,
    }
    for alias, path in aliases.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)")


def create_accrual_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日临时表。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE accrual_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO accrual_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_accrual_quality_asof(connection: DuckDBConnection) -> str:
    """按三张报表均已披露的日期生成年度应计利润截面。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {ACCRUAL_QUALITY_ASOF_TABLE} AS
        WITH annual_income AS (
            SELECT
                ts_code AS symbol,
                end_date,
                f_ann_date AS income_publish_date,
                CAST(n_income_attr_p AS DOUBLE) AS net_income
            FROM accrual_income_db.default_table
            WHERE RIGHT(end_date, 4) = '1231'
              AND f_ann_date IS NOT NULL
              AND n_income_attr_p IS NOT NULL
        ),
        annual_cashflow AS (
            SELECT
                ts_code AS symbol,
                end_date,
                f_ann_date AS cashflow_publish_date,
                CAST(n_cashflow_act AS DOUBLE) AS operating_cashflow
            FROM accrual_cashflow_db.default_table
            WHERE RIGHT(end_date, 4) = '1231'
              AND f_ann_date IS NOT NULL
              AND n_cashflow_act IS NOT NULL
        ),
        annual_balance AS (
            SELECT
                ts_code AS symbol,
                end_date,
                f_ann_date AS balance_publish_date,
                CAST(total_assets AS DOUBLE) AS total_assets
            FROM accrual_balance_db.default_table
            WHERE RIGHT(end_date, 4) = '1231'
              AND f_ann_date IS NOT NULL
              AND total_assets IS NOT NULL
        ),
        aligned AS (
            SELECT
                i.symbol,
                i.end_date,
                CAST(LEFT(i.end_date, 4) AS INTEGER) AS fiscal_year,
                GREATEST(
                    i.income_publish_date,
                    c.cashflow_publish_date,
                    b.balance_publish_date,
                    p.balance_publish_date
                ) AS publish_date,
                i.net_income,
                c.operating_cashflow,
                b.total_assets,
                p.total_assets AS prior_total_assets,
                (b.total_assets + p.total_assets) / 2.0 AS average_total_assets
            FROM annual_income i
            JOIN annual_cashflow c
              ON i.symbol = c.symbol AND i.end_date = c.end_date
            JOIN annual_balance b
              ON i.symbol = b.symbol AND i.end_date = b.end_date
            JOIN annual_balance p
              ON i.symbol = p.symbol
             AND p.end_date = CAST(
                    CAST(LEFT(i.end_date, 4) AS INTEGER) - 1 AS VARCHAR
                 ) || '1231'
            WHERE b.total_assets > 0 AND p.total_assets > 0
        ),
        visible AS (
            SELECT
                d.signal_date,
                a.*,
                (a.net_income - a.operating_cashflow)
                    / a.average_total_assets AS accrual_ratio,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, a.symbol
                    ORDER BY a.fiscal_year DESC, a.publish_date DESC
                ) AS rn
            FROM accrual_signal_dates d
            JOIN aligned a ON a.publish_date <= d.signal_date
            WHERE CAST(LEFT(d.signal_date, 4) AS INTEGER) - a.fiscal_year
                  BETWEEN 1 AND 2
        )
        SELECT
            signal_date,
            symbol,
            end_date,
            fiscal_year,
            publish_date,
            net_income,
            operating_cashflow,
            total_assets,
            prior_total_assets,
            average_total_assets,
            accrual_ratio
        FROM visible
        WHERE rn = 1
        """
    )
    return ACCRUAL_QUALITY_ASOF_TABLE


def load_accrual_quality_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化的应计利润点时截面。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            symbol,
            end_date,
            fiscal_year,
            publish_date,
            net_income,
            operating_cashflow,
            total_assets,
            prior_total_assets,
            average_total_assets,
            accrual_ratio
        FROM {ACCRUAL_QUALITY_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    """信号日统一为 YYYYMMDD。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
