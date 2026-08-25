"""经营现金流收益率所需的年度财务 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


OPERATING_CASHFLOW_YIELD_TABLE = "operating_cashflow_yield_asof"
SIGNAL_DATE_TABLE = "operating_cashflow_yield_signal_dates"


class QueryConnection(Protocol):
    """声明本模块使用的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行查询。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行查询。"""


@dataclass(frozen=True)
class OperatingCashflowYieldPaths:
    """经营现金流和总股本来源。"""

    cashflow: Path
    balance: Path

    def validate(self) -> None:
        """挂载前一次性检查数据文件。"""
        missing = [
            str(path.resolve())
            for path in (self.cashflow, self.balance)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少经营现金流收益率数据文件: {missing}")


def attach_operating_cashflow_yield_databases(
    connection: QueryConnection,
    paths: OperatingCashflowYieldPaths,
) -> None:
    """以只读方式挂载现金流量表和资产负债表。"""
    paths.validate()
    for alias, path in {
        "ocf_yield_cashflow_db": paths.cashflow,
        "ocf_yield_balance_db": paths.balance,
    }.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(
            f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)"
        )


def create_operating_cashflow_yield_signal_dates(
    connection: QueryConnection,
    signal_dates: list[str],
) -> None:
    """建立研究所需的月末信号日表。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {SIGNAL_DATE_TABLE}"
        "(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            f"INSERT INTO {SIGNAL_DATE_TABLE} VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_operating_cashflow_yield_asof(
    connection: QueryConnection,
) -> str:
    """物化每个信号日当时可见的最新年度现金流与总股本。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {OPERATING_CASHFLOW_YIELD_TABLE} AS
        WITH cashflow_source AS (
            SELECT
                ts_code AS symbol,
                end_date,
                COALESCE(NULLIF(f_ann_date, ''), ann_date) AS publish_date,
                CAST(n_cashflow_act AS DOUBLE) AS operating_cashflow,
                ROW_NUMBER() OVER (
                    PARTITION BY ts_code, end_date,
                                 COALESCE(NULLIF(f_ann_date, ''), ann_date)
                    ORDER BY COALESCE(update_flag, '') DESC
                ) AS source_rn
            FROM ocf_yield_cashflow_db.default_table
            WHERE RIGHT(end_date, 4) = '1231'
              AND COALESCE(NULLIF(f_ann_date, ''), ann_date) IS NOT NULL
              AND n_cashflow_act IS NOT NULL
        ),
        balance_source AS (
            SELECT
                ts_code AS symbol,
                end_date,
                COALESCE(NULLIF(f_ann_date, ''), ann_date) AS publish_date,
                CAST(total_share AS DOUBLE) AS total_shares,
                ROW_NUMBER() OVER (
                    PARTITION BY ts_code, end_date,
                                 COALESCE(NULLIF(f_ann_date, ''), ann_date)
                    ORDER BY COALESCE(update_flag, '') DESC
                ) AS source_rn
            FROM ocf_yield_balance_db.default_table
            WHERE RIGHT(end_date, 4) = '1231'
              AND COALESCE(NULLIF(f_ann_date, ''), ann_date) IS NOT NULL
              AND total_share IS NOT NULL
        ),
        cashflow_visible AS (
            SELECT
                d.signal_date,
                c.*,
                ROW_NUMBER() OVER (
                    PARTITION BY d.signal_date, c.symbol, c.end_date
                    ORDER BY c.publish_date DESC
                ) AS visible_rn
            FROM {SIGNAL_DATE_TABLE} d
            JOIN cashflow_source c
              ON c.source_rn = 1 AND c.publish_date <= d.signal_date
        ),
        balance_visible AS (
            SELECT
                d.signal_date,
                b.*,
                ROW_NUMBER() OVER (
                    PARTITION BY d.signal_date, b.symbol, b.end_date
                    ORDER BY b.publish_date DESC
                ) AS visible_rn
            FROM {SIGNAL_DATE_TABLE} d
            JOIN balance_source b
              ON b.source_rn = 1 AND b.publish_date <= d.signal_date
        ),
        paired AS (
            SELECT
                c.signal_date,
                c.symbol,
                c.end_date,
                GREATEST(c.publish_date, b.publish_date) AS f_ann_date,
                c.publish_date AS cashflow_f_ann_date,
                b.publish_date AS balance_f_ann_date,
                c.operating_cashflow,
                b.total_shares,
                ROW_NUMBER() OVER (
                    PARTITION BY c.signal_date, c.symbol
                    ORDER BY c.end_date DESC,
                             GREATEST(c.publish_date, b.publish_date) DESC
                ) AS report_rn
            FROM cashflow_visible c
            JOIN balance_visible b
              ON c.signal_date = b.signal_date
             AND c.symbol = b.symbol
             AND c.end_date = b.end_date
            WHERE c.visible_rn = 1 AND b.visible_rn = 1
        )
        SELECT
            signal_date,
            symbol,
            end_date,
            f_ann_date,
            cashflow_f_ann_date,
            balance_f_ann_date,
            operating_cashflow,
            total_shares
        FROM paired
        WHERE report_rn = 1
        """
    )
    return OPERATING_CASHFLOW_YIELD_TABLE


def load_operating_cashflow_yield_snapshot(
    connection: QueryConnection,
) -> pd.DataFrame:
    """读取标准经营现金流收益率财务截面。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            symbol,
            end_date,
            f_ann_date,
            cashflow_f_ann_date,
            balance_f_ann_date,
            operating_cashflow,
            total_shares
        FROM {OPERATING_CASHFLOW_YIELD_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def load_report_adjustment_factors(
    connection: QueryConnection,
) -> pd.DataFrame:
    """读取报告可见日最近交易日的复权因子。"""
    return connection.execute(
        f"""
        SELECT
            q.signal_date,
            q.symbol,
            a.adj_factor AS report_adj_factor
        FROM (
            SELECT signal_date, symbol, f_ann_date
            FROM {OPERATING_CASHFLOW_YIELD_TABLE}
            ORDER BY symbol, f_ann_date
        ) q
        ASOF LEFT JOIN (
            SELECT ts_code AS symbol, trade_date, adj_factor
            FROM daily_adj_cache
            ORDER BY symbol, trade_date
        ) a
          ON q.symbol = a.symbol AND q.f_ann_date >= a.trade_date
        ORDER BY q.signal_date, q.symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    """统一日期为 YYYYMMDD。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
