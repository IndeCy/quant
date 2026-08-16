"""业绩预告事件的公告日 as-of 数据门面。

因子层只消费本模块物化的点时截面，不能直接读取 forecast.duckdb。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


FORECAST_EVENT_ASOF_TABLE = "forecast_event_asof"


class DuckDBConnection(Protocol):
    """声明预告事件门面所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""


@dataclass(frozen=True)
class ForecastEventPaths:
    """业绩预告数据文件位置。"""

    forecast: Path

    def validate(self) -> None:
        """在挂载前检查文件，避免静默创建空 DuckDB。"""
        if not self.forecast.exists():
            raise FileNotFoundError(f"缺少业绩预告 DuckDB: {self.forecast.resolve()}")


def attach_forecast_database(
    connection: DuckDBConnection,
    paths: ForecastEventPaths,
) -> None:
    """以只读方式挂载业绩预告数据库。"""
    paths.validate()
    escaped = str(paths.forecast.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS forecast_db (READ_ONLY)"
    )


def create_forecast_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """创建研究信号日临时表，统一使用 YYYYMMDD。"""
    normalized = [_normalize_trade_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE forecast_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO forecast_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_forecast_event_asof(
    connection: DuckDBConnection,
    *,
    lookback_days: int,
) -> str:
    """物化每个信号日最近可见的业绩预告事件。

    只允许 ``ann_date <= signal_date``，并按公告日和报告期选择每只股票
    唯一记录。``first_ann_date`` 仅作审计展示，绝不作为数值可见日期。
    """
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {FORECAST_EVENT_ASOF_TABLE} AS
        WITH normalized AS (
            SELECT
                ts_code AS symbol,
                end_date AS report_period,
                ann_date AS publish_date,
                first_ann_date,
                CAST("type" AS VARCHAR) AS forecast_type,
                CAST(p_change_min AS DOUBLE) AS p_change_min,
                CAST(p_change_max AS DOUBLE) AS p_change_max,
                CAST(net_profit_min AS DOUBLE) AS net_profit_min,
                CAST(net_profit_max AS DOUBLE) AS net_profit_max,
                CAST(last_parent_net AS DOUBLE) AS last_parent_net,
                CAST(summary AS VARCHAR) AS summary,
                CAST(change_reason AS VARCHAR) AS change_reason
            FROM forecast_db.default_table
            WHERE ann_date IS NOT NULL
        ),
        ranked AS (
            SELECT
                d.signal_date,
                f.*,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, f.symbol
                    ORDER BY f.report_period DESC, f.publish_date DESC
                ) AS rn
            FROM forecast_signal_dates d
            JOIN normalized f
              ON f.publish_date <= d.signal_date
             AND f.publish_date >= STRFTIME(
                    STRPTIME(d.signal_date, '%Y%m%d')
                    - INTERVAL {int(lookback_days)} DAY,
                    '%Y%m%d'
                 )
        )
        SELECT
            signal_date,
            symbol,
            report_period,
            publish_date,
            first_ann_date,
            forecast_type,
            p_change_min,
            p_change_max,
            (p_change_min + p_change_max) / 2.0 AS p_change_mid,
            net_profit_min,
            net_profit_max,
            last_parent_net,
            summary,
            change_reason
        FROM ranked
        WHERE rn = 1
        """
    )
    return FORECAST_EVENT_ASOF_TABLE


def load_forecast_event_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经通过公告日约束的预告事件截面。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            symbol,
            report_period,
            publish_date,
            first_ann_date,
            forecast_type,
            p_change_min,
            p_change_max,
            p_change_mid,
            net_profit_min,
            net_profit_max,
            last_parent_net,
            summary,
            change_reason
        FROM {FORECAST_EVENT_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_trade_date(value: str) -> str:
    """校验并标准化交易日。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
