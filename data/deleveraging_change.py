"""连续年报资产负债率变化的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


DELEVERAGING_CHANGE_TABLE = "deleveraging_change_asof"


class DuckDBConnection(Protocol):
    """声明去杠杆变化物化需要的最小连接接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class DeleveragingPaths:
    """去杠杆变化只依赖资产负债表。"""

    balance: Path

    def validate(self) -> None:
        """挂载前检查资产负债表数据库。"""
        if not self.balance.exists():
            raise FileNotFoundError(
                f"缺少资产负债表数据库: {self.balance.resolve()}"
            )


def attach_deleveraging_database(
    connection: DuckDBConnection,
    paths: DeleveragingPaths,
) -> None:
    """只读挂载资产负债表。"""
    paths.validate()
    escaped = str(paths.balance.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS deleveraging_db (READ_ONLY)"
    )


def create_deleveraging_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE deleveraging_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO deleveraging_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_deleveraging_change_asof(
    connection: DuckDBConnection,
) -> str:
    """物化最新可见连续年报的资产负债率变化。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {DELEVERAGING_CHANGE_TABLE} AS
        WITH visible AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                b.end_date,
                b.f_ann_date AS publish_date,
                CAST(b.total_assets AS DOUBLE) AS total_assets,
                CAST(b.total_liab AS DOUBLE) AS total_liabilities,
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
            FROM deleveraging_signal_dates d
            JOIN deleveraging_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
              AND CAST(b.comp_type AS VARCHAR) = '1'
              AND CAST(b.report_type AS VARCHAR) IN ('1', '4')
              AND b.total_assets > 0
              AND b.total_liab >= 0
        ),
        annual AS (
            SELECT
                signal_date,
                symbol,
                end_date AS report_period,
                publish_date,
                total_assets,
                total_liabilities,
                total_liabilities / total_assets AS debt_to_assets
            FROM visible
            WHERE revision_rank = 1
        ),
        history AS (
            SELECT
                *,
                LAG(report_period) OVER window_spec AS prior_report_period,
                LAG(publish_date) OVER window_spec AS prior_publish_date,
                LAG(debt_to_assets) OVER window_spec AS prior_debt_to_assets,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY report_period DESC
                ) AS latest_rank
            FROM annual
            WINDOW window_spec AS (
                PARTITION BY signal_date, symbol ORDER BY report_period
            )
        )
        SELECT
            signal_date,
            symbol,
            report_period,
            publish_date,
            prior_report_period,
            prior_publish_date,
            total_assets,
            total_liabilities,
            debt_to_assets,
            prior_debt_to_assets,
            debt_to_assets - prior_debt_to_assets
                AS debt_to_assets_change
        FROM history
        WHERE latest_rank = 1
          AND prior_debt_to_assets IS NOT NULL
          AND CAST(LEFT(report_period, 4) AS INTEGER)
              - CAST(LEFT(prior_report_period, 4) AS INTEGER) = 1
          AND CAST(LEFT(signal_date, 4) AS INTEGER)
              - CAST(LEFT(report_period, 4) AS INTEGER) BETWEEN 1 AND 2
        """
    )
    return DELEVERAGING_CHANGE_TABLE


def load_deleveraging_change_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取去杠杆变化点时截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {DELEVERAGING_CHANGE_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    """只接受 YYYYMMDD 日期。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
