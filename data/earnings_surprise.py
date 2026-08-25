"""标准化意外盈利（SUE）的公告日 as-of 数据门面。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


EARNINGS_SURPRISE_ASOF_TABLE = "earnings_surprise_asof"


class DuckDBConnection(Protocol):
    """声明 SUE 数据门面所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行查询。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行查询。"""


@dataclass(frozen=True)
class EarningsSurprisePaths:
    """SUE 所需的利润表数据库。"""

    income: Path

    def validate(self) -> None:
        """源文件不存在时禁止隐式创建空库。"""
        if not self.income.exists():
            raise FileNotFoundError(
                f"缺少利润表 DuckDB: {self.income.resolve()}"
            )


def attach_earnings_surprise_database(
    connection: DuckDBConnection,
    paths: EarningsSurprisePaths,
) -> None:
    """以只读方式挂载利润表。"""
    paths.validate()
    escaped = str(paths.income.resolve()).replace("'", "''")
    connection.execute(
        f"ATTACH DATABASE '{escaped}' AS sue_income_db (READ_ONLY)"
    )


def create_earnings_surprise_signal_date_table(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日临时表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE sue_signal_dates(signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO sue_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_earnings_surprise_asof(
    connection: DuckDBConnection,
    *,
    history_observations: int = 8,
    max_event_age_days: int = 90,
) -> str:
    """构造仅使用公告前历史误差的季度 SUE 截面。

    EPS 同比变化按相同季度比较，标准差只使用当前报告之前的历史变化。
    当前变化不进入自身分母，避免低估意外程度。
    """
    if history_observations < 2:
        raise ValueError("history_observations must be at least two")
    if max_event_age_days <= 0:
        raise ValueError("max_event_age_days must be positive")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {EARNINGS_SURPRISE_ASOF_TABLE} AS
        WITH quarterly AS (
            SELECT
                ts_code AS symbol,
                end_date,
                f_ann_date AS publish_date,
                CAST(basic_eps AS DOUBLE) AS basic_eps
            FROM sue_income_db.default_table
            WHERE f_ann_date IS NOT NULL
              AND basic_eps IS NOT NULL
              AND RIGHT(end_date, 4) IN ('0331', '0630', '0930', '1231')
        ),
        changes AS (
            SELECT
                current.symbol,
                current.end_date,
                current.publish_date,
                current.basic_eps,
                prior.end_date AS prior_year_end_date,
                prior.publish_date AS prior_year_publish_date,
                prior.basic_eps AS prior_year_basic_eps,
                current.basic_eps - prior.basic_eps AS eps_change
            FROM quarterly current
            JOIN quarterly prior
              ON current.symbol = prior.symbol
             AND prior.end_date =
                 CAST(CAST(LEFT(current.end_date, 4) AS INTEGER) - 1
                      AS VARCHAR)
                 || RIGHT(current.end_date, 4)
            WHERE prior.publish_date < current.publish_date
        ),
        history_ranked AS (
            SELECT
                current.symbol,
                current.end_date,
                current.publish_date,
                current.basic_eps,
                current.prior_year_end_date,
                current.prior_year_publish_date,
                current.prior_year_basic_eps,
                current.eps_change,
                history.eps_change AS historical_eps_change,
                ROW_NUMBER() OVER(
                    PARTITION BY current.symbol, current.end_date
                    ORDER BY history.end_date DESC
                ) AS history_rank
            FROM changes current
            JOIN changes history
              ON current.symbol = history.symbol
             AND history.end_date < current.end_date
             AND history.publish_date < current.publish_date
        ),
        statistics AS (
            SELECT
                symbol,
                end_date,
                publish_date,
                basic_eps,
                prior_year_end_date,
                prior_year_publish_date,
                prior_year_basic_eps,
                eps_change,
                STDDEV_SAMP(historical_eps_change) FILTER(
                    WHERE history_rank <= {int(history_observations)}
                ) AS historical_change_std,
                COUNT(*) FILTER(
                    WHERE history_rank <= {int(history_observations)}
                ) AS history_observations
            FROM history_ranked
            GROUP BY
                symbol,
                end_date,
                publish_date,
                basic_eps,
                prior_year_end_date,
                prior_year_publish_date,
                prior_year_basic_eps,
                eps_change
            HAVING COUNT(*) FILTER(
                WHERE history_rank <= {int(history_observations)}
            ) = {int(history_observations)}
        ),
        events AS (
            SELECT
                *,
                eps_change / NULLIF(historical_change_std, 0) AS sue
            FROM statistics
            WHERE historical_change_std > 0
        ),
        visible AS (
            SELECT
                dates.signal_date,
                events.*,
                DATE_DIFF(
                    'day',
                    STRPTIME(events.publish_date, '%Y%m%d'),
                    STRPTIME(dates.signal_date, '%Y%m%d')
                ) AS event_age_days,
                ROW_NUMBER() OVER(
                    PARTITION BY dates.signal_date, events.symbol
                    ORDER BY events.publish_date DESC, events.end_date DESC
                ) AS recency_rank
            FROM sue_signal_dates dates
            JOIN events
              ON events.publish_date <= dates.signal_date
             AND DATE_DIFF(
                    'day',
                    STRPTIME(events.publish_date, '%Y%m%d'),
                    STRPTIME(dates.signal_date, '%Y%m%d')
                 ) BETWEEN 0 AND {int(max_event_age_days)}
        )
        SELECT
            signal_date,
            symbol,
            end_date,
            publish_date,
            prior_year_end_date,
            prior_year_publish_date,
            basic_eps,
            prior_year_basic_eps,
            eps_change,
            historical_change_std,
            history_observations,
            sue,
            event_age_days
        FROM visible
        WHERE recency_rank = 1
        """
    )
    return EARNINGS_SURPRISE_ASOF_TABLE


def load_earnings_surprise_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经通过公告日和事件时效约束的 SUE 截面。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            symbol,
            end_date,
            publish_date,
            prior_year_end_date,
            prior_year_publish_date,
            basic_eps,
            prior_year_basic_eps,
            eps_change,
            historical_change_std,
            history_observations,
            sue,
            event_age_days
        FROM {EARNINGS_SURPRISE_ASOF_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
