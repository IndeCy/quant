"""个股相对基准的点时滚动 Beta 数据接口。"""

from __future__ import annotations

from typing import Any

import pandas as pd


def attach_rolling_beta(
    connection: Any,
    candidates: pd.DataFrame,
    benchmark_curve: pd.Series,
    *,
    window: int = 120,
    min_observations: int = 100,
) -> pd.DataFrame:
    """在每个信号日附加只使用当日及历史收益计算的滚动 Beta。"""
    if window <= 1:
        raise ValueError("beta window must be greater than 1")
    if not 2 <= min_observations <= window:
        raise ValueError("beta min_observations must be between 2 and window")
    if candidates.empty:
        result = candidates.copy()
        result["beta_120d"] = pd.Series(dtype=float)
        return result
    benchmark = _benchmark_returns(benchmark_curve)
    if benchmark.empty:
        raise ValueError("benchmark curve is empty")
    connection.register("beta_benchmark_returns", benchmark)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE rolling_beta_signal AS
        WITH aligned AS (
            SELECT
                f.trade_date,
                f.symbol,
                f.ret AS stock_return,
                b.market_return
            FROM features f
            JOIN beta_benchmark_returns b ON f.trade_date = b.trade_date
            WHERE f.ret IS NOT NULL AND b.market_return IS NOT NULL
        ),
        rolling AS (
            SELECT
                trade_date,
                symbol,
                COUNT(*) OVER beta_window AS observations,
                COVAR_SAMP(stock_return, market_return) OVER beta_window
                  / NULLIF(VAR_SAMP(market_return) OVER beta_window, 0) AS beta_120d
            FROM aligned
            WINDOW beta_window AS (
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
            )
        )
        SELECT trade_date AS signal_date, symbol, beta_120d
        FROM rolling
        WHERE observations >= {min_observations}
          AND trade_date IN (SELECT signal_date FROM quality_signal_dates)
        """
    )
    beta = connection.execute(
        "SELECT signal_date, symbol, beta_120d FROM rolling_beta_signal"
    ).fetchdf()
    return candidates.merge(beta, on=["signal_date", "symbol"], how="left")


def _benchmark_returns(curve: pd.Series) -> pd.DataFrame:
    values = pd.Series(curve).dropna().astype(float).sort_index()
    values.index = pd.to_datetime(values.index).normalize()
    returns = values.pct_change().dropna()
    return pd.DataFrame(
        {
            "trade_date": returns.index.strftime("%Y%m%d"),
            "market_return": returns.values,
        }
    )
