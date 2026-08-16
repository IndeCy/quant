"""连续年报净股本发行的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


NET_SHARE_ISSUANCE_TABLE = "net_share_issuance_asof"
MATERIAL_ADJ_FACTOR_CHANGE = 0.10


class DuckDBConnection(Protocol):
    """声明净股本发行物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class NetShareIssuancePaths:
    """净股本发行只依赖标准资产负债表。"""

    balance: Path

    def validate(self) -> None:
        """挂载前检查资产负债表文件。"""
        if not self.balance.exists():
            raise FileNotFoundError(
                f"缺少净股本发行资产负债表: {self.balance.resolve()}"
            )


def attach_net_share_issuance_database(
    connection: DuckDBConnection,
    paths: NetShareIssuancePaths,
) -> None:
    """只读挂载资产负债表。"""
    paths.validate()
    escaped = str(paths.balance.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS share_balance_db (READ_ONLY)"
    )


def create_net_share_issuance_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表，所有修订必须在信号日前可见。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE share_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO share_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_net_share_issuance_asof(
    connection: DuckDBConnection,
) -> str:
    """物化最新连续年报股本变化并标记公司行为歧义。"""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {NET_SHARE_ISSUANCE_TABLE} AS
        WITH visible AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                b.end_date,
                b.f_ann_date,
                CAST(b.total_share AS DOUBLE) AS total_shares,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, b.ts_code, b.end_date
                    ORDER BY b.f_ann_date DESC, b.update_flag DESC, b.ann_date DESC
                ) AS revision_rank
            FROM share_signal_dates d
            JOIN share_balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE RIGHT(b.end_date, 4) = '1231'
              AND b.f_ann_date IS NOT NULL
              AND b.total_share > 0
        ),
        history AS (
            SELECT
                signal_date,
                symbol,
                end_date AS report_period,
                f_ann_date AS publish_date,
                total_shares,
                LAG(end_date) OVER window_spec AS prior_report_period,
                LAG(f_ann_date) OVER window_spec AS prior_publish_date,
                LAG(total_shares) OVER window_spec AS prior_total_shares,
                ROW_NUMBER() OVER(
                    PARTITION BY signal_date, symbol
                    ORDER BY end_date DESC
                ) AS latest_rank
            FROM visible
            WHERE revision_rank = 1
            WINDOW window_spec AS (
                PARTITION BY signal_date, symbol ORDER BY end_date
            )
        ),
        pairs AS (
            SELECT
                *,
                total_shares / NULLIF(prior_total_shares, 0) - 1.0
                    AS net_share_growth
            FROM history
            WHERE latest_rank = 1
              AND prior_total_shares > 0
              AND CAST(SUBSTR(report_period, 1, 4) AS INTEGER)
                  - CAST(SUBSTR(prior_report_period, 1, 4) AS INTEGER) = 1
              AND CAST(SUBSTR(signal_date, 1, 4) AS INTEGER)
                  - CAST(SUBSTR(report_period, 1, 4) AS INTEGER) BETWEEN 1 AND 2
        ),
        current_adjustment AS (
            SELECT
                p.*,
                a.adj_factor AS report_adj_factor
            FROM (
                SELECT * FROM pairs ORDER BY symbol, report_period
            ) p
            ASOF LEFT JOIN (
                SELECT
                    ts_code AS symbol,
                    trade_date,
                    adj_factor
                FROM daily_adj_cache
                ORDER BY symbol, trade_date
            ) a
              ON p.symbol = a.symbol AND p.report_period >= a.trade_date
        ),
        both_adjustments AS (
            SELECT
                p.*,
                a.adj_factor AS prior_report_adj_factor
            FROM (
                SELECT * FROM current_adjustment
                ORDER BY symbol, prior_report_period
            ) p
            ASOF LEFT JOIN (
                SELECT
                    ts_code AS symbol,
                    trade_date,
                    adj_factor
                FROM daily_adj_cache
                ORDER BY symbol, trade_date
            ) a
              ON p.symbol = a.symbol
             AND p.prior_report_period >= a.trade_date
        )
        SELECT
            signal_date,
            symbol,
            report_period,
            publish_date,
            prior_report_period,
            prior_publish_date,
            total_shares,
            prior_total_shares,
            net_share_growth,
            report_adj_factor,
            prior_report_adj_factor,
            ABS(
                report_adj_factor / NULLIF(prior_report_adj_factor, 0) - 1.0
            ) AS adj_factor_change,
            report_adj_factor IS NOT NULL
                AND prior_report_adj_factor IS NOT NULL
                AS adjustment_available,
            ABS(net_share_growth) > 1e-12
                AND ABS(
                    report_adj_factor / NULLIF(prior_report_adj_factor, 0) - 1.0
                ) > {MATERIAL_ADJ_FACTOR_CHANGE}
                AS corporate_action_ambiguous
        FROM both_adjustments
        """
    )
    return NET_SHARE_ISSUANCE_TABLE


def load_net_share_issuance_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取净股本发行点时截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {NET_SHARE_ISSUANCE_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
