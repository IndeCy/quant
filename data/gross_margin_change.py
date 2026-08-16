"""连续年报毛利率变化的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


GROSS_MARGIN_CHANGE_TABLE = "gross_margin_change_asof"


class DuckDBConnection(Protocol):
    """声明毛利率变化物化所需的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class GrossMarginFinancialPaths:
    """毛利率变化只依赖标准利润表。"""

    income: Path

    def validate(self) -> None:
        """挂载前检查利润表文件。"""
        if not self.income.exists():
            raise FileNotFoundError(f"缺少利润表 DuckDB: {self.income.resolve()}")


def attach_gross_margin_financial_database(
    connection: DuckDBConnection,
    paths: GrossMarginFinancialPaths,
) -> None:
    """以只读方式挂载利润表。"""
    paths.validate()
    escaped = str(paths.income.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS gross_margin_income_db (READ_ONLY)"
    )


def create_gross_margin_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表，所有财报可见性以该日期为上界。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE gross_margin_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO gross_margin_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_gross_margin_change_asof(
    connection: DuckDBConnection,
) -> str:
    """物化每个信号日可见的最近两份连续年报毛利率变化。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {GROSS_MARGIN_CHANGE_TABLE} AS
        WITH visible AS (
            SELECT
                d.signal_date,
                i.ts_code AS symbol,
                i.end_date,
                i.f_ann_date,
                CAST(i.revenue AS DOUBLE) AS revenue,
                CAST(i.oper_cost AS DOUBLE) AS operating_cost,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, i.ts_code, i.end_date
                    ORDER BY i.f_ann_date DESC, i.update_flag DESC, i.ann_date DESC
                ) AS revision_rank
            FROM gross_margin_signal_dates d
            JOIN gross_margin_income_db.default_table i
              ON i.f_ann_date <= d.signal_date
            WHERE RIGHT(i.end_date, 4) = '1231'
              AND i.f_ann_date IS NOT NULL
        ),
        annual AS (
            SELECT
                signal_date,
                symbol,
                end_date,
                f_ann_date AS publish_date,
                (revenue - operating_cost) / NULLIF(revenue, 0)
                    AS gross_margin
            FROM visible
            WHERE revision_rank = 1
              AND revenue > 0
              AND operating_cost IS NOT NULL
        ),
        history AS (
            SELECT
                *,
                LAG(end_date) OVER window_spec AS prior_report_period,
                LAG(publish_date) OVER window_spec AS prior_publish_date,
                LAG(gross_margin) OVER window_spec AS prior_gross_margin,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY end_date DESC
                ) AS latest_rank
            FROM annual
            WINDOW window_spec AS (
                PARTITION BY signal_date, symbol ORDER BY end_date
            )
        )
        SELECT
            signal_date,
            symbol,
            end_date AS report_period,
            publish_date,
            prior_report_period,
            prior_publish_date,
            gross_margin,
            prior_gross_margin,
            gross_margin - prior_gross_margin AS gross_margin_change
        FROM history
        WHERE latest_rank = 1
          AND prior_gross_margin IS NOT NULL
          AND CAST(SUBSTR(end_date, 1, 4) AS INTEGER)
              - CAST(SUBSTR(prior_report_period, 1, 4) AS INTEGER) = 1
        """
    )
    return GROSS_MARGIN_CHANGE_TABLE


def load_gross_margin_change_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取公告日可见的连续年报毛利率变化截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {GROSS_MARGIN_CHANGE_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
