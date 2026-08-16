"""低特质波动稳健性研究的市场归因与判定工具。"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

import pandas as pd


def market_regression_attribution(
    strategy_values: pd.Series,
    benchmark_curve: pd.Series,
) -> dict[str, float]:
    """用日收益回归拆分市场Beta、年化Alpha与上下行捕获率。"""
    strategy_returns = _normalized_curve(strategy_values).pct_change()
    benchmark_returns = _normalized_curve(benchmark_curve).pct_change()
    aligned = pd.concat(
        [
            strategy_returns.rename("strategy"),
            benchmark_returns.rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 2:
        return _empty_attribution()

    benchmark_variance = float(aligned["benchmark"].var(ddof=1))
    beta = (
        float(aligned["strategy"].cov(aligned["benchmark"]))
        / benchmark_variance
        if benchmark_variance > 0
        else 0.0
    )
    daily_alpha = float(
        aligned["strategy"].mean() - beta * aligned["benchmark"].mean()
    )
    annualized_alpha = (
        math.pow(1.0 + daily_alpha, 252) - 1.0
        if daily_alpha > -1.0
        else -1.0
    )
    correlation = float(aligned["strategy"].corr(aligned["benchmark"]))
    excess = aligned["strategy"] - aligned["benchmark"]
    tracking_error = float(excess.std(ddof=1) * math.sqrt(252))
    information_ratio = (
        float(excess.mean() / excess.std(ddof=1) * math.sqrt(252))
        if excess.std(ddof=1) > 0
        else 0.0
    )
    return {
        "observations": float(len(aligned)),
        "beta": beta,
        "annualized_alpha": float(annualized_alpha),
        "r_squared": correlation * correlation,
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "up_capture": _capture_ratio(aligned, positive=True),
        "down_capture": _capture_ratio(aligned, positive=False),
    }


def summarize_market_attribution(
    by_period: Mapping[str, Mapping[str, float]],
) -> dict[str, float]:
    """汇总非重叠窗口内Alpha为正的广度和Beta稳定性。"""
    if not by_period:
        raise ValueError("market attribution periods are required")
    frame = pd.DataFrame.from_dict(by_period, orient="index")
    return {
        "period_count": float(len(frame)),
        "positive_alpha_share": float(frame["annualized_alpha"].gt(0).mean()),
        "median_annualized_alpha": float(frame["annualized_alpha"].median()),
        "median_beta": float(frame["beta"].median()),
        "maximum_beta": float(frame["beta"].max()),
        "median_up_capture": float(frame["up_capture"].median()),
        "median_down_capture": float(frame["down_capture"].median()),
    }


def classify_return_source(
    *,
    full_attribution: Mapping[str, float],
    period_summary: Mapping[str, float],
    quality_correlation: float,
) -> dict[str, Any]:
    """按预注册门槛区分独立Alpha、共同防御暴露和低Beta。"""
    checks = {
        "full_alpha_at_least_2pct": (
            float(full_attribution["annualized_alpha"]) >= 0.02
        ),
        "positive_alpha_period_share_at_least_75pct": (
            float(period_summary["positive_alpha_share"]) >= 0.75
        ),
        "full_beta_below_090": float(full_attribution["beta"]) < 0.90,
        "down_capture_below_up_capture": (
            float(full_attribution["down_capture"])
            < float(full_attribution["up_capture"])
        ),
        "quality_correlation_at_most_075": quality_correlation <= 0.75,
    }
    alpha_checks = [
        checks["full_alpha_at_least_2pct"],
        checks["positive_alpha_period_share_at_least_75pct"],
    ]
    defensive_checks = [
        checks["full_beta_below_090"],
        checks["down_capture_below_up_capture"],
    ]
    if all(alpha_checks) and all(defensive_checks) and checks[
        "quality_correlation_at_most_075"
    ]:
        label = "INDEPENDENT_DEFENSIVE_ALPHA"
        explanation = "Alpha跨窗口为正、下行捕获较低，且与Quality相关性未超过独立性门槛。"
    elif all(alpha_checks) and all(defensive_checks):
        label = "SHARED_DEFENSIVE_PREMIUM"
        explanation = "具备跨窗口Alpha和防御性，但与Quality高度相关，不能视为独立收益源。"
    elif not any(alpha_checks) and all(defensive_checks):
        label = "LOW_BETA_EXPOSURE_ONLY"
        explanation = "主要表现为低Beta和较低下行捕获，没有稳定的回归Alpha证据。"
    else:
        label = "MIXED_OR_UNSTABLE"
        explanation = "Alpha广度或防御属性未形成一致证据，不能归为稳定独立收益源。"
    return {
        "label": label,
        "explanation": explanation,
        "checks": checks,
    }


def _normalized_curve(series: pd.Series) -> pd.Series:
    """统一日期索引并去除重复观测。"""
    data = pd.to_numeric(series, errors="coerce").dropna().copy()
    data.index = pd.to_datetime(data.index)
    return data[~data.index.duplicated(keep="last")].sort_index()


def _capture_ratio(frame: pd.DataFrame, *, positive: bool) -> float:
    """计算市场上涨或下跌交易日的平均收益捕获率。"""
    mask = frame["benchmark"].gt(0) if positive else frame["benchmark"].lt(0)
    selected = frame[mask]
    benchmark_mean = float(selected["benchmark"].mean()) if not selected.empty else 0.0
    if benchmark_mean == 0:
        return 0.0
    return float(selected["strategy"].mean() / benchmark_mean)


def _empty_attribution() -> dict[str, float]:
    return {
        "observations": 0.0,
        "beta": 0.0,
        "annualized_alpha": 0.0,
        "r_squared": 0.0,
        "tracking_error": 0.0,
        "information_ratio": 0.0,
        "up_capture": 0.0,
        "down_capture": 0.0,
    }
