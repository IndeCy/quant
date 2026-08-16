"""异常存货积累因子的年度财报公告日门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


ABNORMAL_INVENTORY_TABLE = "abnormal_inventory_asof"


class DuckDBConnection(Protocol):
    """声明点时物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class AbnormalInventoryPaths:
    """异常存货因子依赖利润表和资产负债表。"""

    income: Path
    balance: Path

    def validate(self) -> None:
        """挂载前检查源文件，避免意外创建空数据库。"""
        missing = [
            str(path.resolve())
            for path in (self.income, self.balance)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"缺少异常存货财务库: {missing}")


def attach_abnormal_inventory_databases(
    connection: DuckDBConnection,
    paths: AbnormalInventoryPaths,
) -> None:
    """只读挂载利润表和资产负债表。"""
    paths.validate()
    for alias, path in {
        "abnormal_inventory_income_db": paths.income,
        "abnormal_inventory_balance_db": paths.balance,
    }.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(
            f"ATTACH DATABASE '{escaped}' AS {alias} (READ_ONLY)"
        )


def create_abnormal_inventory_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立研究信号日表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE abnormal_inventory_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO abnormal_inventory_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_abnormal_inventory_asof(
    connection: DuckDBConnection,
) -> str:
    """物化信号日已经可见的最新连续两年年报。

    因子定义为 ``ln(存货同比倍数)-ln(营收同比倍数)``。正值表示存货
    增长快于销售，可能反映需求错配；所有报表版本都受 ``f_ann_date``
    约束，且仅使用一般工商业公司的 1231 年报。
    """
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {ABNORMAL_INVENTORY_TABLE} AS
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
            FROM abnormal_inventory_signal_dates d
            JOIN abnormal_inventory_income_db.default_table i
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
                CAST(b.inventories AS DOUBLE) AS inventories,
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
            FROM abnormal_inventory_signal_dates d
            JOIN abnormal_inventory_balance_db.default_table b
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
                b.inventories
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
                LAG(end_date) OVER window_spec AS prior_report_period,
                LAG(publish_date) OVER window_spec AS prior_publish_date,
                LAG(revenue) OVER window_spec AS prior_revenue,
                LAG(inventories) OVER window_spec AS prior_inventories,
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
            income_publish_date,
            balance_publish_date,
            prior_report_period,
            prior_publish_date,
            revenue,
            prior_revenue,
            inventories,
            prior_inventories,
            LN(inventories / prior_inventories)
                AS inventory_log_growth,
            LN(revenue / prior_revenue) AS revenue_log_growth,
            LN(inventories / prior_inventories)
                - LN(revenue / prior_revenue)
                AS abnormal_inventory_accumulation
        FROM history
        WHERE latest_rank = 1
          AND CAST(LEFT(end_date, 4) AS INTEGER)
              - CAST(LEFT(prior_report_period, 4) AS INTEGER) = 1
          AND CAST(LEFT(signal_date, 4) AS INTEGER)
              - CAST(LEFT(end_date, 4) AS INTEGER) BETWEEN 1 AND 2
          AND revenue > 0
          AND prior_revenue > 0
          AND inventories > 0
          AND prior_inventories > 0
        """
    )
    return ABNORMAL_INVENTORY_TABLE


def _normalize_date(value: str) -> str:
    """校验并规范 YYYYMMDD 日期。"""
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
