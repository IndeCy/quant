"""个股相对沪深300的点时滚动下行 Beta 数据门面。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


DOWNSIDE_BETA_TABLE = "downside_beta_features"


class DuckDBConnection(Protocol):
    """声明下行 Beta 物化所需的最小 DuckDB 接口。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行 SQL。"""

    def register(self, name: str, frame: Any) -> Any:
        """注册内存表。"""


def create_downside_beta_signal_dates(
    connection: DuckDBConnection,
    signal_dates: list[str],
) -> None:
    """建立月末信号日表。"""
    normalized = [_normalize_date(value) for value in signal_dates]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE downside_beta_signal_dates("
        "signal_date VARCHAR)"
    )
    if normalized:
        connection.executemany(
            "INSERT INTO downside_beta_signal_dates VALUES (?)",
            [(value,) for value in normalized],
        )


def materialize_downside_beta(
    connection: DuckDBConnection,
    benchmark_curve: pd.Series,
    *,
    window: int = 252,
    min_observations: int = 200,
    min_down_observations: int = 60,
) -> str:
    """只用当日及历史收益计算下行、上行和总 Beta。"""
    if window <= 2:
        raise ValueError("window must be greater than 2")
    if not 2 <= min_observations <= window:
        raise ValueError("invalid min_observations")
    if not 2 <= min_down_observations <= min_observations:
        raise ValueError("invalid min_down_observations")
    benchmark = _benchmark_returns(benchmark_curve)
    if benchmark.empty:
        raise ValueError("benchmark curve is empty")
    connection.register("downside_beta_benchmark", benchmark)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {DOWNSIDE_BETA_TABLE} AS
        WITH aligned AS (
            SELECT
                f.trade_date,
                f.symbol,
                f.ret AS stock_return,
                b.market_return
            FROM features f
            JOIN downside_beta_benchmark b USING(trade_date)
            WHERE f.ret IS NOT NULL
              AND b.market_return IS NOT NULL
        ),
        rolling AS (
            SELECT
                trade_date,
                symbol,
                COUNT(*) OVER beta_window AS observations,
                COUNT(*) FILTER(
                    WHERE market_return < 0
                ) OVER beta_window AS downside_observations,
                COUNT(*) FILTER(
                    WHERE market_return > 0
                ) OVER beta_window AS upside_observations,
                COVAR_SAMP(stock_return, market_return) OVER beta_window
                    / NULLIF(
                        VAR_SAMP(market_return) OVER beta_window,
                        0
                    ) AS total_beta,
                COVAR_SAMP(stock_return, market_return) FILTER(
                    WHERE market_return < 0
                ) OVER beta_window
                    / NULLIF(
                        VAR_SAMP(market_return) FILTER(
                            WHERE market_return < 0
                        ) OVER beta_window,
                        0
                    ) AS downside_beta,
                COVAR_SAMP(stock_return, market_return) FILTER(
                    WHERE market_return > 0
                ) OVER beta_window
                    / NULLIF(
                        VAR_SAMP(market_return) FILTER(
                            WHERE market_return > 0
                        ) OVER beta_window,
                        0
                    ) AS upside_beta
            FROM aligned
            WINDOW beta_window AS (
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
            )
        )
        SELECT
            trade_date AS signal_date,
            symbol,
            observations,
            downside_observations,
            upside_observations,
            total_beta,
            downside_beta,
            upside_beta
        FROM rolling
        WHERE observations >= {min_observations}
          AND downside_observations >= {min_down_observations}
          AND trade_date IN (SELECT signal_date FROM downside_beta_signal_dates)
        """
    )
    return DOWNSIDE_BETA_TABLE


def load_downside_beta_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已经物化的月末下行 Beta 截面。"""
    return connection.execute(
        f"""
        SELECT *
        FROM {DOWNSIDE_BETA_TABLE}
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _benchmark_returns(curve: pd.Series) -> pd.DataFrame:
    """把复权净值曲线转为标准交易日收益。"""
    values = pd.Series(curve).dropna().astype(float).sort_index()
    values.index = pd.to_datetime(values.index).normalize()
    returns = values.pct_change().dropna()
    return pd.DataFrame(
        {
            "trade_date": returns.index.strftime("%Y%m%d"),
            "market_return": returns.values,
        }
    )


def _normalize_date(value: str) -> str:
    """校验并统一日期格式。"""
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid signal date: {value}")
    return normalized
