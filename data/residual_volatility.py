"""相对沪深300ETF的滚动特质波动率研究特征。"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


RESIDUAL_VOLATILITY_TABLE = "residual_volatility"


class DuckDBConnection(Protocol):
    """声明特质波动率物化所需的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行 SQL。"""

    def register(self, name: str, value: Any) -> Any:
        """注册内存数据表。"""


def materialize_residual_volatility(
    connection: DuckDBConnection,
    benchmark_curve: pd.Series,
    *,
    window: int = 120,
    lookback_start: str = "20140101",
    research_start: str = "20150101",
) -> str:
    """按滚动单因子市场模型计算年化残差波动率。"""
    if window <= 2:
        raise ValueError("window must be greater than two")
    if benchmark_curve.empty:
        raise ValueError("benchmark curve is empty")
    lookback = _normalize_date(lookback_start)
    start = _normalize_date(research_start)
    if lookback > start:
        raise ValueError("lookback_start cannot be later than research_start")
    benchmark = pd.DataFrame(
        {
            "trade_date": benchmark_curve.index.strftime("%Y%m%d"),
            "benchmark_close": pd.to_numeric(
                benchmark_curve.values,
                errors="coerce",
            ),
        }
    ).dropna()
    benchmark = benchmark.drop_duplicates("trade_date", keep="last")
    benchmark["benchmark_return"] = benchmark["benchmark_close"].pct_change(
        fill_method=None
    )
    connection.register("residual_volatility_benchmark_input", benchmark)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {RESIDUAL_VOLATILITY_TABLE} AS
        WITH stock_lagged AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                close_qfq,
                LAG(close_qfq) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS prev_close
            FROM daily_adj_cache
            WHERE trade_date >= '{lookback}'
        ),
        aligned AS (
            SELECT
                s.symbol,
                s.trade_date,
                s.close_qfq / NULLIF(s.prev_close, 0) - 1 AS stock_return,
                b.benchmark_return
            FROM stock_lagged s
            JOIN residual_volatility_benchmark_input b USING(trade_date)
            WHERE s.close_qfq > 0
              AND s.prev_close > 0
              AND b.benchmark_return IS NOT NULL
        ),
        rolling AS (
            SELECT
                symbol,
                trade_date,
                COUNT(*) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS observations,
                VAR_SAMP(stock_return) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS stock_variance,
                VAR_SAMP(benchmark_return) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS benchmark_variance,
                COVAR_SAMP(stock_return, benchmark_return) OVER(
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
                ) AS stock_benchmark_covariance
            FROM aligned
        ),
        decomposed AS (
            SELECT
                *,
                stock_benchmark_covariance
                    / NULLIF(benchmark_variance, 0) AS beta,
                GREATEST(
                    stock_variance
                    - POWER(stock_benchmark_covariance, 2)
                        / NULLIF(benchmark_variance, 0),
                    0
                ) AS residual_variance
            FROM rolling
        )
        SELECT
            symbol,
            trade_date,
            beta,
            SQRT(residual_variance) * SQRT(252) AS residual_volatility,
            SQRT(stock_variance) * SQRT(252) AS total_volatility,
            residual_variance,
            observations
        FROM decomposed
        WHERE trade_date >= '{start}'
          AND observations = {window}
          AND benchmark_variance > 0
        """
    )
    return RESIDUAL_VOLATILITY_TABLE


def load_residual_volatility_snapshot(
    connection: DuckDBConnection,
) -> pd.DataFrame:
    """读取已物化的低特质波动研究面板。"""
    return connection.execute(
        f"SELECT * FROM {RESIDUAL_VOLATILITY_TABLE} ORDER BY trade_date, symbol"
    ).fetchdf()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
