"""年度净债务融资现金流的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


NET_DEBT_FINANCING_TABLE = "net_debt_financing_asof"


class DuckDBConnection(Protocol):
    """声明净债务融资物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class NetDebtFinancingPaths:
    """净债务融资依赖现金流量表和资产负债表。"""

    cashflow: Path
    balance: Path

    def validate(self) -> None:
        """挂载前同时检查两张财务库。"""
        missing = [
            str(path.resolve())
            for path in (self.cashflow, self.balance)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少净债务融资财务库: {missing}")


def attach_net_debt_financing_databases(
    connection: DuckDBConnection,
    paths: NetDebtFinancingPaths,
) -> None:
    """只读挂载现金流量表和资产负债表。"""
    paths.validate()
    aliases = {
        "debt_cashflow_db": paths.cashflow,
        "debt_balance_db": paths.balance,
    }
    for alias, path in aliases.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(
            f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)"
        )


def create_net_debt_financing_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立信号日表，报表必须在信号日前实际披露。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE debt_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO debt_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_net_debt_financing_asof(
    connection: DuckDBConnection,
) -> str:
    """物化一般工商业最新年度净债务融资强度。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {NET_DEBT_FINANCING_TABLE} AS
        WITH cashflow_visible AS (
            SELECT
                d.signal_date,
                c.ts_code AS symbol,
                c.end_date,
                c.f_ann_date,
                CAST(c.c_recp_borrow AS DOUBLE) AS borrowing_cash,
                CAST(c.proc_issue_bonds AS DOUBLE) AS bond_issue_cash,
                CAST(c.c_prepay_amt_borr AS DOUBLE) AS debt_repayment_cash,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, c.ts_code, c.end_date
                    ORDER BY
                        c.f_ann_date DESC,
                        c.update_flag DESC,
                        CASE c.report_type
                            WHEN '1' THEN 2 WHEN '4' THEN 1 ELSE 0
                        END DESC,
                        c.ann_date DESC
                ) AS revision_rank
            FROM debt_signal_dates d
            JOIN debt_cashflow_db.default_table c
              ON c.f_ann_date <= d.signal_date
            WHERE RIGHT(c.end_date, 4) = '1231'
              AND c.f_ann_date IS NOT NULL
              AND CAST(c.comp_type AS VARCHAR) = '1'
              AND CAST(c.report_type AS VARCHAR) IN ('1', '4')
        ),
        balance_visible AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                b.end_date,
                b.f_ann_date,
                CAST(b.total_assets AS DOUBLE) AS total_assets,
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
            FROM debt_signal_dates d
            JOIN debt_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
              AND CAST(b.comp_type AS VARCHAR) = '1'
              AND CAST(b.report_type AS VARCHAR) IN ('1', '4')
        ),
        combined AS (
            SELECT
                c.signal_date,
                c.symbol,
                c.end_date AS report_period,
                GREATEST(c.f_ann_date, b.f_ann_date) AS publish_date,
                c.f_ann_date AS cashflow_publish_date,
                b.f_ann_date AS balance_publish_date,
                c.borrowing_cash,
                c.bond_issue_cash,
                c.debt_repayment_cash,
                b.total_assets,
                c.borrowing_cash IS NULL AS borrowing_cash_missing,
                c.bond_issue_cash IS NULL AS bond_issue_cash_missing,
                c.debt_repayment_cash IS NULL AS debt_repayment_cash_missing,
                c.borrowing_cash IS NULL
                    AND c.bond_issue_cash IS NULL
                    AND c.debt_repayment_cash IS NULL
                    AS all_debt_cashflow_missing,
                (
                    COALESCE(c.borrowing_cash, 0)
                    + COALESCE(c.bond_issue_cash, 0)
                    - COALESCE(c.debt_repayment_cash, 0)
                ) / NULLIF(b.total_assets, 0) AS net_debt_financing,
                (
                    COALESCE(c.borrowing_cash, 0)
                    + COALESCE(c.bond_issue_cash, 0)
                    + COALESCE(c.debt_repayment_cash, 0)
                ) / NULLIF(b.total_assets, 0) AS gross_debt_activity,
                ROW_NUMBER() OVER(
                    PARTITION BY c.signal_date, c.symbol
                    ORDER BY c.end_date DESC
                ) AS latest_rank
            FROM cashflow_visible c
            JOIN balance_visible b
              ON c.signal_date = b.signal_date
             AND c.symbol = b.symbol
             AND c.end_date = b.end_date
            WHERE c.revision_rank = 1
              AND b.revision_rank = 1
              AND b.total_assets > 0
        )
        SELECT
            signal_date,
            symbol,
            report_period,
            publish_date,
            cashflow_publish_date,
            balance_publish_date,
            borrowing_cash,
            bond_issue_cash,
            debt_repayment_cash,
            total_assets,
            borrowing_cash_missing,
            bond_issue_cash_missing,
            debt_repayment_cash_missing,
            all_debt_cashflow_missing,
            net_debt_financing,
            gross_debt_activity
        FROM combined
        WHERE latest_rank = 1
          AND CAST(SUBSTR(signal_date, 1, 4) AS INTEGER)
              - CAST(SUBSTR(report_period, 1, 4) AS INTEGER) BETWEEN 1 AND 2
        """
    )
    return NET_DEBT_FINANCING_TABLE


def load_net_debt_financing_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化净债务融资截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {NET_DEBT_FINANCING_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
