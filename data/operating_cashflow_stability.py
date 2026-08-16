"""五年经营现金流稳定性的年度公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


OPERATING_CASHFLOW_STABILITY_TABLE = "operating_cashflow_stability_asof"


class DuckDBConnection(Protocol):
    """声明现金流稳定性物化需要的最小连接接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class OperatingCashflowStabilityPaths:
    """现金流稳定性只依赖现金流量表和资产负债表。"""

    cashflow: Path
    balance: Path

    def validate(self) -> None:
        """两个财务库都存在时才允许挂载。"""
        missing = [
            str(path.resolve())
            for path in (self.cashflow, self.balance)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少经营现金流稳定性数据库: {missing}")


def attach_operating_cashflow_databases(
    connection: DuckDBConnection,
    paths: OperatingCashflowStabilityPaths,
) -> None:
    """只读挂载现金流和资产负债表。"""
    paths.validate()
    for alias, path in {
        "ocf_cashflow_db": paths.cashflow,
        "ocf_balance_db": paths.balance,
    }.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(
            f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)"
        )


def create_operating_cashflow_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE ocf_stability_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO ocf_stability_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_operating_cashflow_stability_asof(
    connection: DuckDBConnection,
) -> str:
    """按信号日物化最近五个连续年报的资产标准化 OCF 波动。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {OPERATING_CASHFLOW_STABILITY_TABLE} AS
        WITH visible_cashflow AS (
            SELECT
                d.signal_date,
                c.ts_code AS symbol,
                c.end_date,
                c.f_ann_date AS cashflow_publish_date,
                CAST(c.n_cashflow_act AS DOUBLE) AS operating_cashflow,
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
            FROM ocf_stability_signal_dates d
            JOIN ocf_cashflow_db.default_table c
              ON c.f_ann_date <= d.signal_date
            WHERE RIGHT(c.end_date, 4) = '1231'
              AND c.f_ann_date IS NOT NULL
              AND CAST(c.comp_type AS VARCHAR) = '1'
              AND CAST(c.report_type AS VARCHAR) IN ('1', '4')
              AND c.n_cashflow_act IS NOT NULL
        ),
        visible_balance AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                b.end_date,
                b.f_ann_date AS balance_publish_date,
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
            FROM ocf_stability_signal_dates d
            JOIN ocf_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
              AND CAST(b.comp_type AS VARCHAR) = '1'
              AND CAST(b.report_type AS VARCHAR) IN ('1', '4')
              AND b.total_assets > 0
        ),
        cashflow_latest AS (
            SELECT * EXCLUDE(revision_rank)
            FROM visible_cashflow
            WHERE revision_rank = 1
        ),
        balance_latest AS (
            SELECT * EXCLUDE(revision_rank)
            FROM visible_balance
            WHERE revision_rank = 1
        ),
        annual_values AS (
            SELECT
                c.signal_date,
                c.symbol,
                c.end_date AS report_period,
                CAST(LEFT(c.end_date, 4) AS INTEGER) AS fiscal_year,
                GREATEST(
                    c.cashflow_publish_date,
                    b.balance_publish_date
                ) AS publish_date,
                c.cashflow_publish_date,
                b.balance_publish_date,
                c.operating_cashflow,
                b.total_assets,
                prior.total_assets AS prior_total_assets,
                c.operating_cashflow
                    / NULLIF(
                        (b.total_assets + prior.total_assets) / 2.0,
                        0
                    ) AS ocf_to_average_assets
            FROM cashflow_latest c
            JOIN balance_latest b
              ON c.signal_date = b.signal_date
             AND c.symbol = b.symbol
             AND c.end_date = b.end_date
            JOIN balance_latest prior
              ON b.signal_date = prior.signal_date
             AND b.symbol = prior.symbol
             AND CAST(LEFT(prior.end_date, 4) AS INTEGER)
                 = CAST(LEFT(b.end_date, 4) AS INTEGER) - 1
            WHERE (b.total_assets + prior.total_assets) > 0
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY fiscal_year DESC, publish_date DESC
                ) AS recency_rank
            FROM annual_values
        ),
        recent_five AS (
            SELECT * FROM ranked WHERE recency_rank <= 5
        ),
        aggregated AS (
            SELECT
                signal_date,
                symbol,
                MAX(fiscal_year) AS latest_fiscal_year,
                MAX(report_period) FILTER(
                    WHERE recency_rank = 1
                ) AS latest_report_period,
                MAX(publish_date) FILTER(
                    WHERE recency_rank = 1
                ) AS latest_publish_date,
                MAX(ocf_to_average_assets) FILTER(
                    WHERE recency_rank = 1
                ) AS current_ocf_to_assets,
                AVG(ocf_to_average_assets) AS ocf_assets_mean_5y,
                MEDIAN(ocf_to_average_assets) AS ocf_assets_median_5y,
                STDDEV_SAMP(ocf_to_average_assets) AS ocf_assets_std_5y,
                COUNT(*) AS observations,
                MAX(fiscal_year) - MIN(fiscal_year) AS fiscal_year_span
            FROM recent_five
            GROUP BY signal_date, symbol
        )
        SELECT * EXCLUDE(fiscal_year_span)
        FROM aggregated
        WHERE observations = 5
          AND fiscal_year_span = 4
          AND CAST(LEFT(signal_date, 4) AS INTEGER) - latest_fiscal_year
              BETWEEN 1 AND 2
        """
    )
    return OPERATING_CASHFLOW_STABILITY_TABLE


def load_operating_cashflow_stability_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取现金流稳定性点时截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {OPERATING_CASHFLOW_STABILITY_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    """只接受 YYYYMMDD 日期。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
