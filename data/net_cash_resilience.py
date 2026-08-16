"""净现金财务韧性因子的年度财报 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


NET_CASH_RESILIENCE_TABLE = "net_cash_resilience_asof"


class DuckDBConnection(Protocol):
    """声明净现金门面所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class NetCashResiliencePaths:
    """声明净现金因子依赖的资产负债表。"""

    balance: Path

    def validate(self) -> None:
        """挂载前检查文件，避免 DuckDB 创建空库。"""
        if not self.balance.exists():
            raise FileNotFoundError(
                f"缺少资产负债表数据库: {self.balance.resolve()}"
            )


def attach_net_cash_database(
    connection: DuckDBConnection,
    paths: NetCashResiliencePaths,
) -> None:
    """以只读方式挂载资产负债表数据库。"""
    paths.validate()
    escaped = str(paths.balance.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS net_cash_balance_db (READ_ONLY)"
    )


def create_net_cash_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表，财报只能向过去连接。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE net_cash_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO net_cash_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_net_cash_resilience_asof(
    connection: DuckDBConnection,
) -> str:
    """按 ``f_ann_date`` 物化最近可见年报的净现金资产比。

    有息债务采用短期借款、长期借款、应付债券、一年内到期非流动负债、
    短期融资款和租赁负债之和。空值按报表无该项目计零，但同时输出
    ``reported_debt_item_count``，供可行性门槛识别数据缺失污染。
    """
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {NET_CASH_RESILIENCE_TABLE} AS
        WITH visible AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                b.end_date AS report_period,
                b.f_ann_date AS publish_date,
                CAST(b.money_cap AS DOUBLE) AS cash_and_equivalents,
                CAST(b.total_assets AS DOUBLE) AS total_assets,
                CAST(b.st_borr AS DOUBLE) AS short_borrowing,
                CAST(b.lt_borr AS DOUBLE) AS long_borrowing,
                CAST(b.bond_payable AS DOUBLE) AS bonds_payable,
                CAST(b.non_cur_liab_due_1y AS DOUBLE)
                    AS noncurrent_due_within_one_year,
                CAST(b.st_fin_payable AS DOUBLE) AS short_financing_payable,
                CAST(b.lease_liab AS DOUBLE) AS lease_liability,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, b.ts_code, b.end_date
                    ORDER BY
                        b.f_ann_date DESC,
                        b.update_flag DESC,
                        CASE b.report_type
                            WHEN '1' THEN 2 WHEN '4' THEN 1 ELSE 0
                        END DESC,
                        b.ann_date DESC
                ) AS revision_rank
            FROM net_cash_signal_dates d
            JOIN net_cash_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
              AND CAST(b.comp_type AS VARCHAR) = '1'
              AND CAST(b.report_type AS VARCHAR) IN ('1', '4')
        ),
        normalized AS (
            SELECT
                *,
                COALESCE(short_borrowing, 0)
                + COALESCE(long_borrowing, 0)
                + COALESCE(bonds_payable, 0)
                + COALESCE(noncurrent_due_within_one_year, 0)
                + COALESCE(short_financing_payable, 0)
                + COALESCE(lease_liability, 0) AS interest_bearing_debt,
                CAST(short_borrowing IS NOT NULL AS INTEGER)
                + CAST(long_borrowing IS NOT NULL AS INTEGER)
                + CAST(bonds_payable IS NOT NULL AS INTEGER)
                + CAST(noncurrent_due_within_one_year IS NOT NULL AS INTEGER)
                + CAST(short_financing_payable IS NOT NULL AS INTEGER)
                + CAST(lease_liability IS NOT NULL AS INTEGER)
                    AS reported_debt_item_count
            FROM visible
            WHERE revision_rank = 1
              AND cash_and_equivalents >= 0
              AND total_assets > 0
              AND COALESCE(short_borrowing, 0) >= 0
              AND COALESCE(long_borrowing, 0) >= 0
              AND COALESCE(bonds_payable, 0) >= 0
              AND COALESCE(noncurrent_due_within_one_year, 0) >= 0
              AND COALESCE(short_financing_payable, 0) >= 0
              AND COALESCE(lease_liability, 0) >= 0
        ),
        ranked AS (
            SELECT
                *,
                (cash_and_equivalents - interest_bearing_debt)
                    / total_assets AS net_cash_to_assets,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY report_period DESC, publish_date DESC
                ) AS latest_rank
            FROM normalized
        )
        SELECT
            signal_date,
            symbol,
            report_period,
            publish_date,
            cash_and_equivalents,
            interest_bearing_debt,
            total_assets,
            net_cash_to_assets,
            reported_debt_item_count
        FROM ranked
        WHERE latest_rank = 1
          AND CAST(LEFT(signal_date, 4) AS INTEGER)
              - CAST(LEFT(report_period, 4) AS INTEGER) BETWEEN 1 AND 2
        """
    )
    return NET_CASH_RESILIENCE_TABLE


def load_net_cash_resilience_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已通过公告日约束的净现金截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {NET_CASH_RESILIENCE_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    """校验并统一信号日为 YYYYMMDD。"""
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
