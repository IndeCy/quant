"""连续年报现金转换周期变化的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


CASH_CONVERSION_CYCLE_TABLE = "cash_conversion_cycle_asof"


class DuckDBConnection(Protocol):
    """声明现金转换周期物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class CashConversionFinancialPaths:
    """现金转换周期依赖利润表和资产负债表。"""

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
            raise FileNotFoundError(f"缺少现金转换周期财务库: {missing}")


def attach_cash_conversion_databases(
    connection: DuckDBConnection,
    paths: CashConversionFinancialPaths,
) -> None:
    """以只读方式挂载利润表和资产负债表。"""
    paths.validate()
    aliases = {
        "ccc_income_db": paths.income,
        "ccc_balance_db": paths.balance,
    }
    for alias, path in aliases.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(
            f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)"
        )


def create_cash_conversion_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立信号日表，禁止读取信号日之后披露或修订的年报。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE cash_conversion_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO cash_conversion_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_cash_conversion_cycle_asof(
    connection: DuckDBConnection,
) -> str:
    """物化一般工商业最新连续年报的现金转换周期变化。

    ``CCC = 应收周转天数 + 存货周转天数 - 应付周转天数``。各余额
    使用期初期末平均值；任一必需字段缺失时保留为空，不做零值填充。
    """
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {CASH_CONVERSION_CYCLE_TABLE} AS
        WITH income_visible AS (
            SELECT
                d.signal_date,
                i.ts_code AS symbol,
                i.end_date,
                i.f_ann_date,
                CAST(i.revenue AS DOUBLE) AS revenue,
                CAST(i.oper_cost AS DOUBLE) AS operating_cost,
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
            FROM cash_conversion_signal_dates d
            JOIN ccc_income_db.default_table i
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
                CAST(b.accounts_receiv AS DOUBLE) AS accounts_receivable,
                CAST(b.inventories AS DOUBLE) AS inventories,
                CAST(b.acct_payable AS DOUBLE) AS accounts_payable,
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
            FROM cash_conversion_signal_dates d
            JOIN ccc_balance_db.default_table b
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
                i.operating_cost,
                b.accounts_receivable,
                b.inventories,
                b.accounts_payable
            FROM income_visible i
            JOIN balance_visible b
              ON i.signal_date = b.signal_date
             AND i.symbol = b.symbol
             AND i.end_date = b.end_date
            WHERE i.revision_rank = 1
              AND b.revision_rank = 1
        ),
        history AS (
            SELECT
                *,
                LAG(end_date, 1) OVER window_spec AS prior_report_period,
                LAG(end_date, 2) OVER window_spec AS prior2_report_period,
                LAG(publish_date, 1) OVER window_spec AS prior_publish_date,
                LAG(publish_date, 2) OVER window_spec AS prior2_publish_date,
                LAG(revenue, 1) OVER window_spec AS prior_revenue,
                LAG(operating_cost, 1) OVER window_spec
                    AS prior_operating_cost,
                LAG(accounts_receivable, 1) OVER window_spec
                    AS prior_accounts_receivable,
                LAG(accounts_receivable, 2) OVER window_spec
                    AS prior2_accounts_receivable,
                LAG(inventories, 1) OVER window_spec AS prior_inventories,
                LAG(inventories, 2) OVER window_spec AS prior2_inventories,
                LAG(accounts_payable, 1) OVER window_spec
                    AS prior_accounts_payable,
                LAG(accounts_payable, 2) OVER window_spec
                    AS prior2_accounts_payable,
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
                365.0 * (accounts_receivable + prior_accounts_receivable)
                    / 2.0 / NULLIF(revenue, 0) AS receivable_days,
                365.0 * (inventories + prior_inventories)
                    / 2.0 / NULLIF(operating_cost, 0) AS inventory_days,
                365.0 * (accounts_payable + prior_accounts_payable)
                    / 2.0 / NULLIF(operating_cost, 0) AS payable_days,
                365.0
                    * (
                        prior_accounts_receivable
                        + prior2_accounts_receivable
                    )
                    / 2.0 / NULLIF(prior_revenue, 0)
                    AS prior_receivable_days,
                365.0 * (prior_inventories + prior2_inventories)
                    / 2.0 / NULLIF(prior_operating_cost, 0)
                    AS prior_inventory_days,
                365.0
                    * (prior_accounts_payable + prior2_accounts_payable)
                    / 2.0 / NULLIF(prior_operating_cost, 0)
                    AS prior_payable_days
            FROM history
            WHERE latest_rank = 1
              AND CAST(SUBSTR(end_date, 1, 4) AS INTEGER)
                  - CAST(SUBSTR(prior_report_period, 1, 4) AS INTEGER) = 1
              AND CAST(SUBSTR(prior_report_period, 1, 4) AS INTEGER)
                  - CAST(SUBSTR(prior2_report_period, 1, 4) AS INTEGER) = 1
        ),
        cycles AS (
            SELECT
                *,
                receivable_days + inventory_days - payable_days
                    AS cash_conversion_cycle,
                prior_receivable_days + prior_inventory_days
                    - prior_payable_days AS prior_cash_conversion_cycle
            FROM ratios
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
            operating_cost,
            accounts_receivable,
            inventories,
            accounts_payable,
            prior_revenue,
            prior_operating_cost,
            prior_accounts_receivable,
            prior_inventories,
            prior_accounts_payable,
            prior2_accounts_receivable,
            prior2_inventories,
            prior2_accounts_payable,
            receivable_days,
            inventory_days,
            payable_days,
            prior_receivable_days,
            prior_inventory_days,
            prior_payable_days,
            cash_conversion_cycle,
            prior_cash_conversion_cycle,
            cash_conversion_cycle - prior_cash_conversion_cycle
                AS cash_conversion_cycle_change,
            revenue IS NULL OR revenue <= 0
                OR operating_cost IS NULL OR operating_cost <= 0
                OR prior_revenue IS NULL OR prior_revenue <= 0
                OR prior_operating_cost IS NULL OR prior_operating_cost <= 0
                OR accounts_receivable IS NULL
                OR inventories IS NULL
                OR accounts_payable IS NULL
                OR prior_accounts_receivable IS NULL
                OR prior_inventories IS NULL
                OR prior_accounts_payable IS NULL
                OR prior2_accounts_receivable IS NULL
                OR prior2_inventories IS NULL
                OR prior2_accounts_payable IS NULL
                AS required_component_missing
        FROM cycles
        WHERE CAST(SUBSTR(signal_date, 1, 4) AS INTEGER)
              - CAST(SUBSTR(end_date, 1, 4) AS INTEGER) BETWEEN 1 AND 2
        """
    )
    return CASH_CONVERSION_CYCLE_TABLE


def load_cash_conversion_cycle_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化的现金转换周期截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {CASH_CONVERSION_CYCLE_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
