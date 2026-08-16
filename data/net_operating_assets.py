"""净经营资产异常因子的年度公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


NET_OPERATING_ASSETS_TABLE = "net_operating_assets_asof"


class DuckDBConnection(Protocol):
    """声明净经营资产物化需要的最小连接接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class NetOperatingAssetsPaths:
    """净经营资产只依赖资产负债表。"""

    balance: Path

    def validate(self) -> None:
        """挂载前检查本地财务库。"""
        if not self.balance.exists():
            raise FileNotFoundError(
                f"缺少资产负债表数据库: {self.balance.resolve()}"
            )


def attach_net_operating_assets_database(
    connection: DuckDBConnection,
    paths: NetOperatingAssetsPaths,
) -> None:
    """只读挂载资产负债表。"""
    paths.validate()
    escaped = str(paths.balance.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS noa_balance_db (READ_ONLY)"
    )


def create_net_operating_assets_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE noa_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO noa_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_net_operating_assets_asof(
    connection: DuckDBConnection,
) -> str:
    """物化一般工商业最新可见年度 NOA 强度。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {NET_OPERATING_ASSETS_TABLE} AS
        WITH visible AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                b.end_date,
                b.f_ann_date,
                CAST(b.total_assets AS DOUBLE) AS total_assets,
                CAST(b.total_liab AS DOUBLE) AS total_liab,
                CAST(b.money_cap AS DOUBLE) AS money_cap,
                CAST(b.trad_asset AS DOUBLE) AS trad_asset,
                CAST(b.st_borr AS DOUBLE) AS st_borr,
                CAST(b.lt_borr AS DOUBLE) AS lt_borr,
                CAST(b.bond_payable AS DOUBLE) AS bond_payable,
                CAST(b.st_bonds_payable AS DOUBLE) AS st_bonds_payable,
                CAST(b.non_cur_liab_due_1y AS DOUBLE)
                    AS non_cur_liab_due_1y,
                CAST(b.lease_liab AS DOUBLE) AS lease_liab,
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
            FROM noa_signal_dates d
            JOIN noa_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
              AND CAST(b.comp_type AS VARCHAR) = '1'
              AND CAST(b.report_type AS VARCHAR) IN ('1', '4')
        ),
        calculated AS (
            SELECT
                signal_date,
                symbol,
                end_date AS report_period,
                f_ann_date AS publish_date,
                total_assets,
                total_liab,
                money_cap,
                trad_asset,
                st_borr,
                lt_borr,
                bond_payable,
                st_bonds_payable,
                non_cur_liab_due_1y,
                lease_liab,
                (
                    total_assets
                    - COALESCE(money_cap, 0)
                    - COALESCE(trad_asset, 0)
                ) AS operating_assets,
                (
                    total_liab
                    - COALESCE(st_borr, 0)
                    - COALESCE(lt_borr, 0)
                    - COALESCE(bond_payable, 0)
                    - COALESCE(st_bonds_payable, 0)
                    - COALESCE(non_cur_liab_due_1y, 0)
                    - COALESCE(lease_liab, 0)
                ) AS operating_liabilities,
                (
                    (
                        total_assets
                        - COALESCE(money_cap, 0)
                        - COALESCE(trad_asset, 0)
                    )
                    - (
                        total_liab
                        - COALESCE(st_borr, 0)
                        - COALESCE(lt_borr, 0)
                        - COALESCE(bond_payable, 0)
                        - COALESCE(st_bonds_payable, 0)
                        - COALESCE(non_cur_liab_due_1y, 0)
                        - COALESCE(lease_liab, 0)
                    )
                ) AS net_operating_assets,
                (
                    (
                        total_assets
                        - COALESCE(money_cap, 0)
                        - COALESCE(trad_asset, 0)
                    )
                    - (
                        total_liab
                        - COALESCE(st_borr, 0)
                        - COALESCE(lt_borr, 0)
                        - COALESCE(bond_payable, 0)
                        - COALESCE(st_bonds_payable, 0)
                        - COALESCE(non_cur_liab_due_1y, 0)
                        - COALESCE(lease_liab, 0)
                    )
                ) / NULLIF(total_assets, 0) AS noa_ratio,
                money_cap IS NULL AS money_cap_missing,
                trad_asset IS NULL AS trad_asset_missing,
                (
                    st_borr IS NULL
                    AND lt_borr IS NULL
                    AND bond_payable IS NULL
                    AND st_bonds_payable IS NULL
                    AND non_cur_liab_due_1y IS NULL
                    AND lease_liab IS NULL
                ) AS all_debt_components_missing,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY end_date DESC
                ) AS latest_rank
            FROM visible
            WHERE revision_rank = 1
              AND total_assets > 0
              AND total_liab IS NOT NULL
              AND money_cap IS NOT NULL
        )
        SELECT *
        EXCLUDE(latest_rank)
        FROM calculated
        WHERE latest_rank = 1
          AND CAST(SUBSTR(signal_date, 1, 4) AS INTEGER)
              - CAST(SUBSTR(report_period, 1, 4) AS INTEGER) BETWEEN 1 AND 2
        """
    )
    return NET_OPERATING_ASSETS_TABLE


def load_net_operating_assets_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化的点时截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {NET_OPERATING_ASSETS_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
