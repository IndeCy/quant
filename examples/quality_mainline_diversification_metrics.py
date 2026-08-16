"""Quality 防御与主线链动组合的纯指标计算。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def build_period_metrics(
    daily: pd.DataFrame,
    periods: dict[str, tuple[str, str]],
) -> dict[str, dict[str, dict[str, float]]]:
    """统一计算组合、核心、卫星和基准指标。"""
    result: dict[str, dict[str, dict[str, float]]] = {}
    for period, (start, end) in periods.items():
        sliced = daily[daily["trade_date"].between(start, end)].copy()
        years = max((len(sliced) - 1) / 252.0, 1.0 / 252.0)
        annual_turnover = float(sliced["allocation_turnover"].sum() / years)
        result[period] = {
            "combined": metric_summary(
                sliced["portfolio_nav"],
                sliced["benchmark_nav"],
                annual_turnover,
            ),
            "core": metric_summary(
                sliced["core_nav"],
                sliced["benchmark_nav"],
                0.0,
            ),
            "satellite": metric_summary(
                sliced["satellite_nav"],
                sliced["benchmark_nav"],
                0.0,
            ),
        }
    return result


def metric_summary(
    nav: pd.Series,
    benchmark_nav: pd.Series,
    annual_turnover: float,
) -> dict[str, float]:
    """对任意共同区间净值计算可比较指标。"""
    values = nav.astype(float).reset_index(drop=True)
    benchmark = benchmark_nav.astype(float).reset_index(drop=True)
    if len(values) < 2:
        raise ValueError("period requires at least two observations")
    normalized = values / float(values.iloc[0])
    benchmark_normalized = benchmark / float(benchmark.iloc[0])
    returns = normalized.pct_change().dropna()
    years = (len(normalized) - 1) / 252.0
    annualized = float(normalized.iloc[-1] ** (1.0 / years) - 1.0)
    drawdown = normalized / normalized.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    volatility = float(returns.std(ddof=1))
    sharpe = (
        float(returns.mean() / volatility * math.sqrt(252))
        if volatility > 0
        else 0.0
    )
    return {
        "annualized_return": annualized,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "calmar": annualized / abs(max_drawdown) if max_drawdown < 0 else 0.0,
        "excess_return": float(
            normalized.iloc[-1] - benchmark_normalized.iloc[-1]
        ),
        "annual_turnover": annual_turnover,
    }


def build_period_correlations(
    daily: pd.DataFrame,
    periods: dict[str, tuple[str, str]],
) -> dict[str, float]:
    """计算核心与卫星日收益相关性。"""
    return {
        name: float(
            daily.loc[
                daily["trade_date"].between(start, end),
                ["core_return", "satellite_return"],
            ].corr().iloc[0, 1]
        )
        for name, (start, end) in periods.items()
    }


def build_annual_returns(daily: pd.DataFrame) -> pd.DataFrame:
    """按自然年输出三条资产收益和组合回撤。"""
    frame = daily.copy()
    frame["year"] = frame["trade_date"].str[:4]
    rows: list[dict[str, Any]] = []
    for year, group in frame.groupby("year", sort=True):
        rows.append(
            {
                "year": year,
                "combined_return": _period_return(group["portfolio_nav"]),
                "core_return": _period_return(group["core_nav"]),
                "satellite_return": _period_return(group["satellite_nav"]),
                "combined_max_drawdown": float(
                    (
                        group["portfolio_nav"]
                        / group["portfolio_nav"].cummax()
                        - 1
                    ).min()
                ),
            }
        )
    return pd.DataFrame(rows)


def build_drawdown_attribution(daily: pd.DataFrame) -> dict[str, Any]:
    """定位组合最大回撤窗口，并比较两个袖套同期表现。"""
    nav = daily.set_index("trade_date")["portfolio_nav"].astype(float)
    drawdown = nav / nav.cummax() - 1.0
    trough = str(drawdown.idxmin())
    peak = str(nav.loc[:trough].idxmax())
    window = daily[daily["trade_date"].between(peak, trough)].copy()
    return {
        "peak_date": peak,
        "trough_date": trough,
        "combined_return": _period_return(window["portfolio_nav"]),
        "core_return": _period_return(window["core_nav"]),
        "satellite_return": _period_return(window["satellite_nav"]),
        "benchmark_return": _period_return(window["benchmark_nav"]),
    }


def _period_return(values: pd.Series) -> float:
    data = values.astype(float)
    return float(data.iloc[-1] / data.iloc[0] - 1.0) if len(data) >= 2 else 0.0
