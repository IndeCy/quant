"""主线链动策略的收益集中度、尾部损失和回撤恢复指标。"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def build_tail_profile(
    nav: pd.Series,
    *,
    episode_threshold: float = -0.10,
) -> dict[str, Any]:
    """从净成本净值构造完整尾部风险画像。"""
    values = _normalized_nav(nav)
    returns = values.pct_change().dropna()
    log_returns = np.log1p(returns)
    running_peak = values.cummax()
    drawdown = values / running_peak - 1.0
    years = (len(values) - 1) / 252.0
    positive_logs = log_returns[log_returns.gt(0)].sort_values(ascending=False)
    best_ten = returns.nlargest(10)
    without_best_ten_log = float(log_returns.drop(index=best_ten.index).sum())
    annualized_without_best_ten = (
        math.exp(without_best_ten_log / years) - 1.0
        if years > 0
        else 0.0
    )
    quantile_05 = float(returns.quantile(0.05))
    expected_shortfall = float(returns[returns.le(quantile_05)].mean())
    annual_returns = values.groupby(values.index.year).apply(
        lambda group: float(group.iloc[-1] / group.iloc[0] - 1.0)
        if len(group) >= 2
        else 0.0
    )
    episodes = build_drawdown_episodes(
        values,
        threshold=episode_threshold,
    )
    return {
        "annualized_return": float(
            math.exp(float(log_returns.sum()) / years) - 1.0
        ),
        "max_drawdown": float(drawdown.min()),
        "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)),
        "sharpe": (
            float(returns.mean() / returns.std(ddof=1) * math.sqrt(252))
            if returns.std(ddof=1) > 0
            else 0.0
        ),
        "var_95": quantile_05,
        "expected_shortfall_95": expected_shortfall,
        "skewness": float(returns.skew()),
        "excess_kurtosis": float(returns.kurt()),
        "best_day": float(returns.max()),
        "worst_day": float(returns.min()),
        "top10_positive_log_contribution": (
            float(positive_logs.head(10).sum() / positive_logs.sum())
            if positive_logs.sum() > 0
            else 0.0
        ),
        "annualized_return_without_best_10_days": annualized_without_best_ten,
        "positive_year_share": float(annual_returns.gt(0).mean()),
        "positive_year_count": int(annual_returns.gt(0).sum()),
        "year_count": int(len(annual_returns)),
        "drawdown_episode_count": int(len(episodes)),
        "maximum_underwater_days": int(
            max((episode["underwater_days"] for episode in episodes), default=0)
        ),
        "maximum_recovery_days": int(
            max((episode["recovery_days"] for episode in episodes), default=0)
        ),
        "episodes": episodes,
        "best_10_days": _dated_values(best_ten),
        "worst_10_days": _dated_values(returns.nsmallest(10)),
        "annual_returns": {
            str(year): float(value)
            for year, value in annual_returns.items()
        },
    }


def build_drawdown_episodes(
    nav: pd.Series,
    *,
    threshold: float = -0.10,
) -> list[dict[str, Any]]:
    """识别跌破阈值后直到收复前高的完整水下区间。"""
    if not -1 < threshold < 0:
        raise ValueError("drawdown episode threshold must be between -1 and 0")
    values = _normalized_nav(nav)
    dates = list(values.index)
    peak_value = float(values.iloc[0])
    peak_position = 0
    active: dict[str, Any] | None = None
    episodes: list[dict[str, Any]] = []
    for position, (date, value_raw) in enumerate(values.items()):
        value = float(value_raw)
        if active is None and value >= peak_value:
            peak_value = value
            peak_position = position
        drawdown = value / peak_value - 1.0
        if active is None and drawdown <= threshold:
            active = {
                "peak_date": dates[peak_position],
                "peak_position": peak_position,
                "peak_value": peak_value,
                "trough_date": date,
                "trough_position": position,
                "trough_drawdown": drawdown,
            }
        elif active is not None and drawdown < active["trough_drawdown"]:
            active["trough_date"] = date
            active["trough_position"] = position
            active["trough_drawdown"] = drawdown
        if active is not None and value >= active["peak_value"]:
            episodes.append(
                _close_episode(active, date, position, recovered=True)
            )
            active = None
            peak_value = value
            peak_position = position
    if active is not None:
        episodes.append(
            _close_episode(
                active,
                dates[-1],
                len(dates) - 1,
                recovered=False,
            )
        )
    return sorted(
        episodes,
        key=lambda item: item["trough_drawdown"],
    )


def evaluate_tail_gate(profile: dict[str, Any]) -> dict[str, Any]:
    """应用预注册的长期观察风险门槛。"""
    checks = {
        "max_drawdown_within_35pct": profile["max_drawdown"] >= -0.35,
        "underwater_period_within_252_days": (
            profile["maximum_underwater_days"] <= 252
        ),
        "top10_positive_contribution_at_most_35pct": (
            profile["top10_positive_log_contribution"] <= 0.35
        ),
        "positive_return_without_best_10_days": (
            profile["annualized_return_without_best_10_days"] > 0
        ),
        "expected_shortfall_within_4pct": (
            profile["expected_shortfall_95"] >= -0.04
        ),
        "positive_year_share_at_least_60pct": (
            profile["positive_year_share"] >= 0.60
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
    }


def _close_episode(
    active: dict[str, Any],
    end_date: pd.Timestamp,
    end_position: int,
    *,
    recovered: bool,
) -> dict[str, Any]:
    """把内部位置转换成稳定可序列化的回撤记录。"""
    return {
        "peak_date": pd.Timestamp(active["peak_date"]).strftime("%Y%m%d"),
        "trough_date": pd.Timestamp(active["trough_date"]).strftime("%Y%m%d"),
        "recovery_date": (
            pd.Timestamp(end_date).strftime("%Y%m%d") if recovered else ""
        ),
        "trough_drawdown": float(active["trough_drawdown"]),
        "underwater_days": int(end_position - active["peak_position"]),
        "recovery_days": int(end_position - active["trough_position"]),
        "recovered": bool(recovered),
    }


def _normalized_nav(nav: pd.Series) -> pd.Series:
    values = pd.to_numeric(nav, errors="coerce").dropna().copy()
    values.index = pd.to_datetime(values.index)
    values = values[~values.index.duplicated(keep="last")].sort_index()
    if len(values) < 2 or values.le(0).any():
        raise ValueError("tail profile requires positive nav observations")
    return values / float(values.iloc[0])


def _dated_values(series: pd.Series) -> list[dict[str, Any]]:
    return [
        {
            "trade_date": pd.Timestamp(date).strftime("%Y%m%d"),
            "return": float(value),
        }
        for date, value in series.items()
    ]
