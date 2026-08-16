"""连续年报资产周转率变化的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


ASSET_TURNOVER_CHANGE_TABLE = "asset_turnover_change_asof"


class DuckDBConnection(Protocol):
    """声明资产周转率物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class AssetTurnoverFinancialPaths:
    """资产周转率变化依赖利润表和资产负债表。"""

    income: Path
    balance: Path

    def validate(self) -> None:
        """挂载前同时检查两张财务库。"""
        missing = [
            str(path.resolve())
            for path in (self.income, self.balance)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少资产周转率财务库: {missing}")


def attach_asset_turnover_databases(
    connection: DuckDBConnection,
    paths: AssetTurnoverFinancialPaths,
) -> None:
    """以只读方式挂载利润表和资产负债表。"""
    paths.validate()
    aliases = {
        "turnover_income_db": paths.income,
        "turnover_balance_db": paths.balance,
    }
    for alias, path in aliases.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(
            f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)"
        )


def create_asset_turnover_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立信号日表，所有财务值必须在信号日前可见。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE asset_turnover_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO asset_turnover_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_asset_turnover_change_asof(
    connection: DuckDBConnection,
) -> str:
    """物化一般工商业最新连续年报的资产周转率变化。

    当年周转率使用 ``当年营收 / 平均(当年总资产, 上年总资产)``；
    上年周转率使用相同口径，因此至少需要三份连续资产负债表。
    """
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {ASSET_TURNOVER_CHANGE_TABLE} AS
        WITH income_visible AS (
            SELECT
                d.signal_date,
                i.ts_code AS symbol,
                i.end_date,
                i.f_ann_date,
                CAST(i.revenue AS DOUBLE) AS revenue,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, i.ts_code, i.end_date
                    ORDER BY
                        i.f_ann_date DESC,
                        i.update_flag DESC,
                        CASE i.report_type
                            WHEN '1' THEN 2 WHEN '4' THEN 1 ELSE 0
                        END DESC,
                        i.ann_date DESC
                ) AS revision_rank
            FROM asset_turnover_signal_dates d
            JOIN turnover_income_db.default_table i
              ON i.f_ann_date <= d.signal_date
            WHERE RIGHT(i.end_date, 4) = '1231'
              AND i.f_ann_date IS NOT NULL
              AND CAST(i.comp_type AS VARCHAR) = '1'
              AND CAST(i.report_type AS VARCHAR) IN ('1', '4')
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
            FROM asset_turnover_signal_dates d
            JOIN turnover_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
              AND CAST(b.comp_type AS VARCHAR) = '1'
              AND CAST(b.report_type AS VARCHAR) IN ('1', '4')
        ),
        annual AS (
            SELECT
                i.signal_date,
                i.symbol,
                i.end_date,
                GREATEST(i.f_ann_date, b.f_ann_date) AS publish_date,
                i.f_ann_date AS income_publish_date,
                b.f_ann_date AS balance_publish_date,
                i.revenue,
                b.total_assets
            FROM income_visible i
            JOIN balance_visible b
              ON i.signal_date = b.signal_date
             AND i.symbol = b.symbol
             AND i.end_date = b.end_date
            WHERE i.revision_rank = 1
              AND b.revision_rank = 1
              AND i.revenue > 0
              AND b.total_assets > 0
        ),
        history AS (
            SELECT
                *,
                LAG(end_date, 1) OVER window_spec AS prior_report_period,
                LAG(end_date, 2) OVER window_spec AS prior2_report_period,
                LAG(publish_date, 1) OVER window_spec AS prior_publish_date,
                LAG(publish_date, 2) OVER window_spec AS prior2_publish_date,
                LAG(revenue, 1) OVER window_spec AS prior_revenue,
                LAG(total_assets, 1) OVER window_spec AS prior_total_assets,
                LAG(total_assets, 2) OVER window_spec AS prior2_total_assets,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY end_date DESC
                ) AS latest_rank
            FROM annual
            WINDOW window_spec AS (
                PARTITION BY signal_date, symbol ORDER BY end_date
            )
        ),
        ratios AS (
            SELECT
                *,
                revenue
                    / NULLIF((total_assets + prior_total_assets) / 2.0, 0)
                    AS asset_turnover,
                prior_revenue
                    / NULLIF(
                        (prior_total_assets + prior2_total_assets) / 2.0,
                        0
                    )
                    AS prior_asset_turnover
            FROM history
            WHERE latest_rank = 1
              AND CAST(SUBSTR(end_date, 1, 4) AS INTEGER)
                  - CAST(SUBSTR(prior_report_period, 1, 4) AS INTEGER) = 1
              AND CAST(SUBSTR(prior_report_period, 1, 4) AS INTEGER)
                  - CAST(SUBSTR(prior2_report_period, 1, 4) AS INTEGER) = 1
        )
        SELECT
            signal_date,
            symbol,
            end_date AS report_period,
            publish_date,
            income_publish_date,
            balance_publish_date,
            prior_report_period,
            prior_publish_date,
            prior2_report_period,
            prior2_publish_date,
            revenue,
            prior_revenue,
            total_assets,
            prior_total_assets,
            prior2_total_assets,
            asset_turnover,
            prior_asset_turnover,
            asset_turnover - prior_asset_turnover AS asset_turnover_change
        FROM ratios
        WHERE asset_turnover IS NOT NULL
          AND prior_asset_turnover IS NOT NULL
          AND CAST(SUBSTR(signal_date, 1, 4) AS INTEGER)
              - CAST(SUBSTR(end_date, 1, 4) AS INTEGER) BETWEEN 1 AND 2
        """
    )
    return ASSET_TURNOVER_CHANGE_TABLE


def load_asset_turnover_change_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经物化的资产周转率变化截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {ASSET_TURNOVER_CHANGE_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
