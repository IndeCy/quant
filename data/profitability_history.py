"""长期盈利稳定性因子的 DuckDB as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


PROFITABILITY_FLOOR_ASOF_TABLE = "profitability_floor_asof"


class DuckDBConnection(Protocol):
    """声明长期盈利门面需要的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class ProfitabilityHistoryPaths:
    """ROA 指标和三张财务报表路径。"""

    indicator: Path
    income: Path
    balance: Path
    cashflow: Path

    def validate(self) -> None:
        """全部源库存在时才允许挂载。"""
        missing = [
            str(path.resolve())
            for path in (
                self.indicator,
                self.income,
                self.balance,
                self.cashflow,
            )
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少盈利历史数据库: {missing}")


def attach_profitability_history_databases(
    connection: DuckDBConnection,
    paths: ProfitabilityHistoryPaths,
) -> None:
    """只读挂载盈利历史所需数据库。"""
    paths.validate()
    aliases = {
        "profit_indicator_db": paths.indicator,
        "profit_income_db": paths.income,
        "profit_balance_db": paths.balance,
        "profit_cashflow_db": paths.cashflow,
    }
    for alias, path in aliases.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)")


def create_profitability_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日临时表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE profitability_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO profitability_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_profitability_floor_asof(connection: DuckDBConnection) -> str:
    """按公告日生成最近五个连续年报的最低 ROA。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {PROFITABILITY_FLOOR_ASOF_TABLE} AS
        WITH publish_dates AS (
            SELECT ts_code, end_date, MAX(f_ann_date) AS publish_date
            FROM (
                SELECT ts_code, end_date, f_ann_date
                FROM profit_income_db.default_table
                WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date
                FROM profit_balance_db.default_table
                WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date
                FROM profit_cashflow_db.default_table
                WHERE f_ann_date IS NOT NULL
            )
            WHERE RIGHT(end_date, 4) = '1231'
            GROUP BY ts_code, end_date
        ),
        annual_roa AS (
            SELECT
                f.ts_code AS symbol,
                f.end_date,
                CAST(LEFT(f.end_date, 4) AS INTEGER) AS fiscal_year,
                p.publish_date,
                CAST(f.roa AS DOUBLE) AS roa
            FROM profit_indicator_db.default_table f
            JOIN publish_dates p
              ON f.ts_code = p.ts_code AND f.end_date = p.end_date
            WHERE RIGHT(f.end_date, 4) = '1231'
              AND f.roa IS NOT NULL
        ),
        ranked AS (
            SELECT
                d.signal_date,
                a.*,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, a.symbol
                    ORDER BY a.fiscal_year DESC, a.publish_date DESC
                ) AS recency_rank
            FROM profitability_signal_dates d
            JOIN annual_roa a ON a.publish_date <= d.signal_date
        ),
        recent_five AS (
            SELECT * FROM ranked WHERE recency_rank <= 5
        ),
        aggregated AS (
            SELECT
                signal_date,
                symbol,
                MAX(fiscal_year) AS latest_fiscal_year,
                MAX(publish_date) FILTER(
                    WHERE recency_rank = 1
                ) AS latest_publish_date,
                MAX(roa) FILTER(WHERE recency_rank = 1) AS current_roa,
                MIN(roa) AS roa_floor_5y,
                AVG(roa) AS roa_mean_5y,
                STDDEV_SAMP(roa) AS roa_std_5y,
                COUNT(*) AS observations,
                MAX(fiscal_year) - MIN(fiscal_year) AS fiscal_year_span
            FROM recent_five
            GROUP BY signal_date, symbol
        )
        SELECT
            signal_date,
            symbol,
            latest_fiscal_year,
            latest_publish_date,
            current_roa,
            roa_floor_5y,
            roa_mean_5y,
            roa_std_5y,
            observations
        FROM aggregated
        WHERE observations = 5
          AND fiscal_year_span = 4
          AND CAST(LEFT(signal_date, 4) AS INTEGER) - latest_fiscal_year
              BETWEEN 1 AND 2
        """
    )
    return PROFITABILITY_FLOOR_ASOF_TABLE


def load_profitability_floor_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取五年盈利底线点时截面。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            symbol,
            latest_fiscal_year,
            latest_publish_date,
            current_roa,
            roa_floor_5y,
            roa_mean_5y,
            roa_std_5y,
            observations
        FROM {PROFITABILITY_FLOOR_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    """只接受 YYYYMMDD 日期。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
