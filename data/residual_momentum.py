"""走步双因子残差动量的点时行情特征门面。"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
import pandas as pd


RESIDUAL_MOMENTUM_TABLE = "residual_momentum_features"
STYLE_INPUT_TABLE = "residual_momentum_style_input"
SIGNAL_DATE_TABLE = "residual_momentum_signal_dates"


class DuckDBConnection(Protocol):
    """声明残差动量物化需要的最小连接能力。"""

    def execute(self, query: str, parameters: Any = None) -> Any:
        """执行SQL。"""

    def executemany(self, query: str, parameters: Any) -> Any:
        """批量执行SQL。"""

    def register(self, name: str, value: Any) -> Any:
        """注册内存表。"""


def build_style_factor_frame(
    hs300_curve: pd.Series,
    csi500_curve: pd.Series,
) -> pd.DataFrame:
    """构造沪深300收益和中证500相对沪深300收益。"""
    curves = pd.concat(
        [
            _normalized_curve(hs300_curve).rename("hs300"),
            _normalized_curve(csi500_curve).rename("csi500"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(curves) < 3:
        raise ValueError("残差动量风格行情不足3日")
    frame = pd.DataFrame(index=curves.index)
    frame["market_return"] = curves["hs300"].pct_change(fill_method=None)
    frame["size_return"] = (
        curves["csi500"].pct_change(fill_method=None)
        - frame["market_return"]
    )
    frame["trade_date"] = frame.index.strftime("%Y%m%d")
    frame["trade_index"] = np.arange(len(frame), dtype=int)
    return frame[
        ["trade_date", "trade_index", "market_return", "size_return"]
    ].reset_index(drop=True)


def materialize_residual_momentum(
    connection: DuckDBConnection,
    style_factors: pd.DataFrame,
    signal_dates: list[str],
    *,
    estimation_start_lag: int = 252,
    estimation_end_lag: int = 121,
    evaluation_start_lag: int = 120,
    evaluation_end_lag: int = 20,
    minimum_estimation_observations: int = 120,
    minimum_evaluation_observations: int = 90,
    source_start: str = "20130101",
) -> str:
    """先估计历史Beta，再用后续跳月窗口累计特质收益。"""
    _validate_windows(
        estimation_start_lag,
        estimation_end_lag,
        evaluation_start_lag,
        evaluation_end_lag,
        minimum_estimation_observations,
        minimum_evaluation_observations,
    )
    normalized_dates = [_normalize_date(value) for value in signal_dates]
    source = _normalize_date(source_start)
    required_columns = {
        "trade_date",
        "trade_index",
        "market_return",
        "size_return",
    }
    missing = sorted(required_columns.difference(style_factors.columns))
    if missing:
        raise ValueError(f"残差动量风格输入缺少字段: {missing}")
    connection.register(STYLE_INPUT_TABLE, style_factors)
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {SIGNAL_DATE_TABLE}(signal_date VARCHAR)"
    )
    if normalized_dates:
        connection.executemany(
            f"INSERT INTO {SIGNAL_DATE_TABLE} VALUES (?)",
            [(value,) for value in normalized_dates],
        )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {RESIDUAL_MOMENTUM_TABLE} AS
        WITH stock_lagged AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                close_qfq,
                LAG(close_qfq) OVER(
                    PARTITION BY ts_code ORDER BY trade_date
                ) AS previous_close
            FROM daily_adj_cache
            WHERE trade_date >= '{source}'
        ),
        aligned AS (
            SELECT
                s.symbol,
                s.trade_date,
                b.trade_index,
                s.close_qfq / NULLIF(s.previous_close, 0) - 1.0
                    AS stock_return,
                b.market_return,
                b.size_return
            FROM stock_lagged s
            JOIN {STYLE_INPUT_TABLE} b USING(trade_date)
            WHERE s.close_qfq > 0
              AND s.previous_close > 0
              AND b.market_return IS NOT NULL
              AND b.size_return IS NOT NULL
        ),
        signal_index AS (
            SELECT d.signal_date, b.trade_index AS signal_index
            FROM {SIGNAL_DATE_TABLE} d
            JOIN {STYLE_INPUT_TABLE} b
              ON d.signal_date = b.trade_date
        ),
        estimation AS (
            SELECT
                d.signal_date,
                d.signal_index,
                r.symbol,
                COUNT(*) AS estimation_observations,
                MAX(r.trade_index) AS estimation_max_index,
                VAR_SAMP(r.market_return) AS market_variance,
                VAR_SAMP(r.size_return) AS size_variance,
                COVAR_SAMP(r.market_return, r.size_return)
                    AS market_size_covariance,
                COVAR_SAMP(r.stock_return, r.market_return)
                    AS stock_market_covariance,
                COVAR_SAMP(r.stock_return, r.size_return)
                    AS stock_size_covariance
            FROM signal_index d
            JOIN aligned r
              ON r.trade_index BETWEEN
                 d.signal_index - {estimation_start_lag}
                 AND d.signal_index - {estimation_end_lag}
            GROUP BY d.signal_date, d.signal_index, r.symbol
        ),
        identified AS (
            SELECT
                *,
                market_variance * size_variance
                    - POWER(market_size_covariance, 2) AS determinant
            FROM estimation
            WHERE estimation_observations
                  >= {minimum_estimation_observations}
        ),
        betas AS (
            SELECT
                *,
                (
                    stock_market_covariance * size_variance
                    - stock_size_covariance * market_size_covariance
                ) / NULLIF(determinant, 0) AS market_beta,
                (
                    stock_size_covariance * market_variance
                    - stock_market_covariance * market_size_covariance
                ) / NULLIF(determinant, 0) AS size_beta
            FROM identified
            WHERE determinant > 1e-16
        ),
        evaluated AS (
            SELECT
                b.signal_date,
                b.signal_index,
                b.symbol,
                b.market_beta,
                b.size_beta,
                b.determinant,
                b.estimation_observations,
                b.estimation_max_index,
                COUNT(*) AS evaluation_observations,
                MAX(r.trade_index) AS evaluation_max_index,
                SUM(r.stock_return) AS evaluation_stock_sum,
                SUM(r.market_return) AS evaluation_market_sum,
                SUM(r.size_return) AS evaluation_size_sum,
                SUM(
                    r.stock_return
                    - b.market_beta * r.market_return
                    - b.size_beta * r.size_return
                ) AS residual_momentum,
                STDDEV_SAMP(
                    r.stock_return
                    - b.market_beta * r.market_return
                    - b.size_beta * r.size_return
                ) AS residual_volatility
            FROM betas b
            JOIN aligned r
              ON r.symbol = b.symbol
             AND r.trade_index BETWEEN
                 b.signal_index - {evaluation_start_lag}
                 AND b.signal_index - {evaluation_end_lag}
            GROUP BY
                b.signal_date, b.signal_index, b.symbol,
                b.market_beta, b.size_beta, b.determinant,
                b.estimation_observations, b.estimation_max_index
        )
        SELECT *
        FROM evaluated
        WHERE evaluation_observations >= {minimum_evaluation_observations}
          AND residual_momentum IS NOT NULL
          AND residual_volatility IS NOT NULL
        """
    )
    return RESIDUAL_MOMENTUM_TABLE


def _validate_windows(
    estimation_start_lag: int,
    estimation_end_lag: int,
    evaluation_start_lag: int,
    evaluation_end_lag: int,
    minimum_estimation_observations: int,
    minimum_evaluation_observations: int,
) -> None:
    """确保估计窗、评价窗和跳过窗口严格分离。"""
    if not (
        estimation_start_lag > estimation_end_lag
        > evaluation_start_lag > evaluation_end_lag > 0
    ):
        raise ValueError("残差动量窗口必须严格按时间先后分离")
    estimation_capacity = estimation_start_lag - estimation_end_lag + 1
    evaluation_capacity = evaluation_start_lag - evaluation_end_lag + 1
    if not 3 <= minimum_estimation_observations <= estimation_capacity:
        raise ValueError("估计窗口最小观测数无效")
    if not 2 <= minimum_evaluation_observations <= evaluation_capacity:
        raise ValueError("评价窗口最小观测数无效")


def _normalized_curve(curve: pd.Series) -> pd.Series:
    values = pd.to_numeric(curve, errors="coerce").dropna().copy()
    values.index = pd.to_datetime(values.index)
    values = values[~values.index.duplicated(keep="last")].sort_index()
    if values.empty or values.le(0).any():
        raise ValueError("风格净值必须为正")
    return values / float(values.iloc[0])


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid trade date: {value}")
    return normalized
