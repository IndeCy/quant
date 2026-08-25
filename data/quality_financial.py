"""Quality 财务因子的 DuckDB as-of 数据门面。

该模块是 Quality 因子访问原始财务表的唯一入口。调用方只能得到满足
`f_ann_date <= signal_date` 的标准快照，不能自行按报告期拼接财报。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


QUALITY_ASOF_TABLE = "financial_quality_asof"
QUALITY_ANNUAL_ASOF_TABLE = "financial_quality_asof_annual"
_ALLOWED_OUTPUT_TABLES = {QUALITY_ASOF_TABLE, QUALITY_ANNUAL_ASOF_TABLE}


class DuckDBConnection(Protocol):
    """声明本模块需要的最小 DuckDB 连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class QualityFinancialPaths:
    """Quality 指标及公告日期来源库。"""

    indicator: Path
    income: Path
    balance: Path
    cashflow: Path

    def validate(self) -> None:
        """在连接前检查全部财务库，失败时不产生部分挂载。"""
        missing = [str(path.resolve()) for path in self.all_paths() if not path.exists()]
        if missing:
            raise FileNotFoundError(f"缺少财务 DuckDB 数据文件: {missing}")

    def all_paths(self) -> tuple[Path, ...]:
        """按稳定顺序返回全部数据文件。"""
        return self.indicator, self.income, self.balance, self.cashflow


def attach_quality_financial_databases(
    connection: DuckDBConnection,
    paths: QualityFinancialPaths,
) -> None:
    """只读挂载 Quality 所需财务库。"""
    paths.validate()
    aliases = {
        "fina_db": paths.indicator,
        "income_db": paths.income,
        "balance_db": paths.balance,
        "cashflow_db": paths.cashflow,
    }
    for alias, path in aliases.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)")


def create_quality_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日临时表，日期为空时保留空表。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute("CREATE OR REPLACE TEMP TABLE quality_signal_dates(signal_date VARCHAR)")
    if normalized:
        connection.executemany(
            "INSERT INTO quality_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_quality_financial_asof(
    connection: DuckDBConnection,
    *,
    annual_only: bool,
) -> str:
    """物化 Quality 财务截面，并返回稳定临时表名。"""
    output_table = QUALITY_ANNUAL_ASOF_TABLE if annual_only else QUALITY_ASOF_TABLE
    if output_table not in _ALLOWED_OUTPUT_TABLES:
        raise ValueError(f"unsupported quality as-of table: {output_table}")
    annual_clause = "WHERE RIGHT(end_date, 4) = '1231'" if annual_only else ""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {output_table} AS
        WITH publish_dates AS (
            SELECT ts_code, end_date, MAX(f_ann_date) AS f_ann_date
            FROM (
                SELECT ts_code, end_date, f_ann_date FROM income_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM balance_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM cashflow_db.default_table WHERE f_ann_date IS NOT NULL
            )
            {annual_clause}
            GROUP BY ts_code, end_date
        ),
        clean_fina AS (
            SELECT
                f.ts_code AS symbol,
                f.end_date,
                p.f_ann_date,
                CAST(f.roe AS DOUBLE) AS roe,
                CAST(f.roa AS DOUBLE) AS roa,
                CAST(f.ocf_to_or AS DOUBLE) AS ocf_to_or,
                CAST(f.ocf_to_profit AS DOUBLE) AS ocf_to_profit,
                CAST(f.grossprofit_margin AS DOUBLE) AS grossprofit_margin,
                CAST(f.netprofit_margin AS DOUBLE) AS netprofit_margin,
                CAST(f.assets_yoy AS DOUBLE) AS assets_yoy,
                CAST(f.roic AS DOUBLE) AS roic,
                CAST(f.assets_turn AS DOUBLE) AS assets_turn,
                CAST(f.salescash_to_or AS DOUBLE) AS salescash_to_or,
                CAST(f.dtprofit_to_profit AS DOUBLE) AS dtprofit_to_profit,
                CAST(f.netprofit_yoy AS DOUBLE) AS netprofit_yoy,
                CAST(f.eps AS DOUBLE) AS eps,
                CAST(f.bps AS DOUBLE) AS bps,
                CAST(f.debt_to_assets AS DOUBLE) AS debt_to_assets,
                CAST(f.tr_yoy AS DOUBLE) AS tr_yoy
            FROM fina_db.default_table f
            JOIN publish_dates p ON f.ts_code = p.ts_code AND f.end_date = p.end_date
            WHERE p.f_ann_date IS NOT NULL
        ),
        ranked AS (
            SELECT
                d.signal_date,
                q.*,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, q.symbol
                    ORDER BY q.end_date DESC, q.f_ann_date DESC
                ) AS rn
            FROM quality_signal_dates d
            JOIN clean_fina q ON q.f_ann_date <= d.signal_date
        )
        SELECT signal_date, symbol, end_date, f_ann_date,
               roe, roa, ocf_to_or, ocf_to_profit, grossprofit_margin,
               netprofit_margin, assets_yoy, roic, assets_turn,
               salescash_to_or, dtprofit_to_profit, netprofit_yoy,
               eps, bps, debt_to_assets, tr_yoy
        FROM ranked
        WHERE rn = 1
        """
    )
    return output_table


def load_quality_financial_snapshot(
    connection: DuckDBConnection,
    *,
    annual_only: bool = True,
) -> pd.DataFrame:
    """读取已经物化的标准 Quality 财务截面。"""
    table = QUALITY_ANNUAL_ASOF_TABLE if annual_only else QUALITY_ASOF_TABLE
    return connection.execute(
        f"""
        SELECT signal_date, symbol, end_date, f_ann_date,
               roe, roa, ocf_to_or, ocf_to_profit, grossprofit_margin,
               netprofit_margin, assets_yoy, roic, assets_turn,
               salescash_to_or, dtprofit_to_profit, netprofit_yoy,
               eps, bps, debt_to_assets, tr_yoy
        FROM {table}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    """信号日统一为 YYYYMMDD，避免 DuckDB 隐式日期比较。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
