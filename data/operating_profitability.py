"""Fama-French 经营盈利能力的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


OPERATING_PROFITABILITY_TABLE = "operating_profitability_asof"


class DuckDBConnection(Protocol):
    """声明经营盈利能力物化需要的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class OperatingProfitabilityPaths:
    """经营盈利能力依赖的标准财务库。"""

    income: Path
    balance: Path

    def validate(self) -> None:
        """挂载前检查数据文件，避免只连接一半财务口径。"""
        missing = [
            str(path.resolve())
            for path in (self.income, self.balance)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少经营盈利能力财务库: {missing}")


def attach_operating_profitability_databases(
    connection: DuckDBConnection,
    paths: OperatingProfitabilityPaths,
) -> None:
    """只读挂载利润表和资产负债表。"""
    paths.validate()
    aliases = {
        "op_income_db": paths.income,
        "op_balance_db": paths.balance,
    }
    for alias, path in aliases.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(
            f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)"
        )


def create_operating_profitability_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表，财务可见性以信号日为上界。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE op_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO op_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_operating_profitability_asof(
    connection: DuckDBConnection,
) -> str:
    """物化每个信号日可见的最新年度经营盈利能力。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {OPERATING_PROFITABILITY_TABLE} AS
        WITH visible_income AS (
            SELECT
                d.signal_date,
                i.ts_code AS symbol,
                i.end_date,
                i.f_ann_date,
                CAST(i.revenue AS DOUBLE) AS revenue,
                CAST(i.oper_cost AS DOUBLE) AS operating_cost,
                CAST(i.sell_exp AS DOUBLE) AS selling_expense,
                CAST(i.admin_exp AS DOUBLE) AS admin_expense,
                COALESCE(
                    CAST(i.fin_exp_int_exp AS DOUBLE),
                    CAST(i.int_exp AS DOUBLE)
                ) AS interest_expense,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, i.ts_code, i.end_date
                    ORDER BY i.f_ann_date DESC, i.update_flag DESC, i.ann_date DESC
                ) AS revision_rank
            FROM op_signal_dates d
            JOIN op_income_db.default_table i
              ON i.f_ann_date <= d.signal_date
            WHERE RIGHT(i.end_date, 4) = '1231'
              AND i.f_ann_date IS NOT NULL
        ),
        visible_balance AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                b.end_date,
                b.f_ann_date,
                CAST(b.total_hldr_eqy_inc_min_int AS DOUBLE) AS book_equity,
                CAST(b.total_assets AS DOUBLE) AS total_assets,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, b.ts_code, b.end_date
                    ORDER BY b.f_ann_date DESC, b.update_flag DESC, b.ann_date DESC
                ) AS revision_rank
            FROM op_signal_dates d
            JOIN op_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
        ),
        combined AS (
            SELECT
                i.signal_date,
                i.symbol,
                i.end_date AS report_period,
                GREATEST(i.f_ann_date, b.f_ann_date) AS publish_date,
                i.f_ann_date AS income_publish_date,
                b.f_ann_date AS balance_publish_date,
                i.revenue,
                i.operating_cost,
                i.selling_expense,
                i.admin_expense,
                i.interest_expense,
                b.book_equity,
                b.total_assets,
                i.selling_expense IS NULL AS selling_expense_missing,
                i.admin_expense IS NULL AS admin_expense_missing,
                i.interest_expense IS NULL AS interest_expense_missing,
                (
                    i.revenue
                    - i.operating_cost
                    - COALESCE(i.selling_expense, 0)
                    - COALESCE(i.admin_expense, 0)
                    - COALESCE(i.interest_expense, 0)
                ) / NULLIF(b.book_equity, 0) AS operating_profitability,
                (i.revenue - i.operating_cost)
                    / NULLIF(b.total_assets, 0) AS gross_profitability,
                ROW_NUMBER() OVER(
                    PARTITION BY i.signal_date, i.symbol
                    ORDER BY i.end_date DESC
                ) AS latest_rank
            FROM visible_income i
            JOIN visible_balance b
              ON i.signal_date = b.signal_date
             AND i.symbol = b.symbol
             AND i.end_date = b.end_date
            WHERE i.revision_rank = 1
              AND b.revision_rank = 1
              AND i.revenue > 0
              AND i.operating_cost IS NOT NULL
              AND b.book_equity > 0
              AND b.total_assets > 0
        )
        SELECT
            signal_date,
            symbol,
            report_period,
            publish_date,
            income_publish_date,
            balance_publish_date,
            revenue,
            operating_cost,
            selling_expense,
            admin_expense,
            interest_expense,
            book_equity,
            total_assets,
            selling_expense_missing,
            admin_expense_missing,
            interest_expense_missing,
            operating_profitability,
            gross_profitability
        FROM combined
        WHERE latest_rank = 1
          AND CAST(SUBSTR(signal_date, 1, 4) AS INTEGER)
              - CAST(SUBSTR(report_period, 1, 4) AS INTEGER) BETWEEN 1 AND 2
        """
    )
    return OPERATING_PROFITABILITY_TABLE


def load_operating_profitability_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化的经营盈利能力截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {OPERATING_PROFITABILITY_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
