"""连续年报 ROA 改善的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


PROFITABILITY_IMPROVEMENT_TABLE = "profitability_improvement_asof"


class DuckDBConnection(Protocol):
    """声明 ROA 改善物化所需的最小连接接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class ProfitabilityImprovementPaths:
    """ROA 改善只依赖利润表和资产负债表。"""

    income: Path
    balance: Path

    def validate(self) -> None:
        """挂载前检查两张财务数据库。"""
        for label, path in [
            ("利润表", self.income),
            ("资产负债表", self.balance),
        ]:
            if not path.exists():
                raise FileNotFoundError(f"缺少{label}数据库: {path.resolve()}")


def attach_profitability_improvement_databases(
    connection: DuckDBConnection,
    paths: ProfitabilityImprovementPaths,
) -> None:
    """以只读方式挂载利润表和资产负债表。"""
    paths.validate()
    income = str(paths.income.resolve()).replace("'", "''")
    balance = str(paths.balance.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{income}' AS profitability_income_db (READ_ONLY)"
    )
    connection.execute(
        f"ATTACH DATABASE '{balance}' AS profitability_balance_db (READ_ONLY)"
    )


def create_profitability_improvement_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立研究月末信号日表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE profitability_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO profitability_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_profitability_improvement_asof(
    connection: DuckDBConnection,
) -> str:
    """物化最新可见连续年报的 ROA 水平及年度变化。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {PROFITABILITY_IMPROVEMENT_TABLE} AS
        WITH income_visible AS (
            SELECT
                d.signal_date,
                i.ts_code AS symbol,
                i.end_date,
                i.f_ann_date,
                CAST(i.n_income_attr_p AS DOUBLE) AS net_income,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, i.ts_code, i.end_date
                    ORDER BY i.f_ann_date DESC, i.update_flag DESC,
                             i.ann_date DESC
                ) AS revision_rank
            FROM profitability_signal_dates d
            JOIN profitability_income_db.default_table i
              ON i.f_ann_date <= d.signal_date
            WHERE RIGHT(i.end_date, 4) = '1231'
              AND i.f_ann_date IS NOT NULL
              AND CAST(i.comp_type AS VARCHAR) = '1'
              AND CAST(i.report_type AS VARCHAR) IN ('1', '4')
              AND i.n_income_attr_p IS NOT NULL
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
                    ORDER BY b.f_ann_date DESC, b.update_flag DESC,
                             b.ann_date DESC
                ) AS revision_rank
            FROM profitability_signal_dates d
            JOIN profitability_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
              AND CAST(b.comp_type AS VARCHAR) = '1'
              AND CAST(b.report_type AS VARCHAR) IN ('1', '4')
              AND b.total_assets > 0
        ),
        annual AS (
            SELECT
                i.signal_date,
                i.symbol,
                i.end_date AS report_period,
                GREATEST(i.f_ann_date, b.f_ann_date) AS publish_date,
                i.net_income,
                b.total_assets
            FROM income_visible i
            JOIN balance_visible b
              ON i.signal_date = b.signal_date
             AND i.symbol = b.symbol
             AND i.end_date = b.end_date
            WHERE i.revision_rank = 1 AND b.revision_rank = 1
        ),
        history AS (
            SELECT
                *,
                LAG(report_period, 1) OVER window_spec AS prior_report_period,
                LAG(report_period, 2) OVER window_spec AS prior2_report_period,
                LAG(net_income, 1) OVER window_spec AS prior_net_income,
                LAG(total_assets, 1) OVER window_spec AS prior_total_assets,
                LAG(total_assets, 2) OVER window_spec AS prior2_total_assets,
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
            prior2_report_period,
            net_income / NULLIF(prior_total_assets, 0) AS current_roa,
            prior_net_income / NULLIF(prior2_total_assets, 0) AS prior_roa,
            net_income / NULLIF(prior_total_assets, 0)
              - prior_net_income / NULLIF(prior2_total_assets, 0)
                AS roa_change
        FROM history
        WHERE latest_rank = 1
          AND prior_net_income IS NOT NULL
          AND prior_total_assets > 0
          AND prior2_total_assets > 0
          AND CAST(LEFT(report_period, 4) AS INTEGER)
              - CAST(LEFT(prior_report_period, 4) AS INTEGER) = 1
          AND CAST(LEFT(report_period, 4) AS INTEGER)
              - CAST(LEFT(prior2_report_period, 4) AS INTEGER) = 2
          AND CAST(LEFT(signal_date, 4) AS INTEGER)
              - CAST(LEFT(report_period, 4) AS INTEGER) BETWEEN 1 AND 2
        """
    )
    return PROFITABILITY_IMPROVEMENT_TABLE


def load_profitability_improvement_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取 ROA 改善点时截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {PROFITABILITY_IMPROVEMENT_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    """只接受 YYYYMMDD 日期。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
