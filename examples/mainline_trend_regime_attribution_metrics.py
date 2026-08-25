"""主线链动趋势状态归因的纯计算函数。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


REGIME_ORDER = [
    "UP_POSITIVE",
    "UP_NONPOSITIVE",
    "RISK_POSITIVE",
    "RISK_NONPOSITIVE",
]


def classify_lagged_trend_regime(
    market: pd.DataFrame,
    *,
    return_window: int = 20,
) -> pd.DataFrame:
    """用 T 日收盘状态标记 T+1 收益，避免状态归因偷看当日结果。"""
    if market.empty or return_window <= 0:
        return pd.DataFrame(
            columns=["trade_date", "state_asof_date", "regime"]
        )
    frame = market.sort_values("trade_date").copy()
    frame["trade_date"] = frame["trade_date"].astype(str)
    nav = pd.to_numeric(frame["benchmark_nav"], errors="coerce")
    frame["market_return_window"] = nav / nav.shift(return_window) - 1.0
    trend = frame["trend_state"].astype(str)
    momentum = frame["market_return_window"]
    frame["close_regime"] = pd.NA
    frame.loc[
        (trend == "UP") & (momentum > 0), "close_regime"
    ] = "UP_POSITIVE"
    frame.loc[
        (trend == "UP") & (momentum <= 0), "close_regime"
    ] = "UP_NONPOSITIVE"
    frame.loc[
        (trend == "RISK") & (momentum > 0), "close_regime"
    ] = "RISK_POSITIVE"
    frame.loc[
        (trend == "RISK") & (momentum <= 0), "close_regime"
    ] = "RISK_NONPOSITIVE"
    frame["state_asof_date"] = frame["trade_date"].shift(1)
    frame["regime"] = frame["close_regime"].shift(1)
    return frame[
        ["trade_date", "state_asof_date", "regime"]
    ].dropna(subset=["regime"])


def attach_regimes(
    daily: pd.DataFrame,
    regimes: pd.DataFrame,
) -> pd.DataFrame:
    """把可见状态合并到三个袖套的次日收益。"""
    frame = daily.sort_values("trade_date").copy()
    frame["combined_return_net"] = (
        pd.to_numeric(frame["portfolio_nav"], errors="coerce")
        .pct_change()
        .fillna(0.0)
    )
    result = frame.merge(
        regimes,
        on="trade_date",
        how="inner",
        validate="one_to_one",
    )
    return result.sort_values("trade_date").reset_index(drop=True)


def build_regime_metrics(
    daily: pd.DataFrame,
    periods: dict[str, tuple[str, str]],
) -> pd.DataFrame:
    """逐阶段、逐状态计算核心、卫星和组合条件表现。"""
    rows: list[dict[str, Any]] = []
    for period, (start, end) in periods.items():
        period_frame = daily[daily["trade_date"].between(start, end)]
        period_days = len(period_frame)
        for regime in REGIME_ORDER:
            selected = period_frame[period_frame["regime"] == regime]
            if selected.empty:
                continue
            core = metric_summary(selected["core_return"])
            satellite = metric_summary(selected["satellite_return"])
            combined = metric_summary(selected["combined_return_net"])
            rows.append(
                {
                    "period": period,
                    "regime": regime,
                    "days": len(selected),
                    "day_share": (
                        len(selected) / period_days if period_days else 0.0
                    ),
                    **_prefix("core", core),
                    **_prefix("satellite", satellite),
                    **_prefix("combined", combined),
                    "satellite_annual_lift_vs_core": (
                        satellite["annualized_return"]
                        - core["annualized_return"]
                    ),
                    "combined_annual_lift_vs_core": (
                        combined["annualized_return"]
                        - core["annualized_return"]
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_episode_metrics(daily: pd.DataFrame) -> pd.DataFrame:
    """统计连续状态段，避免只看拼接后的条件收益。"""
    if daily.empty:
        return pd.DataFrame()
    frame = daily.sort_values("trade_date").copy()
    frame["episode_id"] = frame["regime"].ne(frame["regime"].shift()).cumsum()
    rows: list[dict[str, Any]] = []
    for _, group in frame.groupby("episode_id", sort=True):
        rows.append(
            {
                "regime": str(group.iloc[0]["regime"]),
                "start_date": str(group.iloc[0]["trade_date"]),
                "end_date": str(group.iloc[-1]["trade_date"]),
                "days": len(group),
                "satellite_return": _total_return(
                    group["satellite_return"]
                ),
                "core_return": _total_return(group["core_return"]),
                "combined_return": _total_return(
                    group["combined_return_net"]
                ),
            }
        )
    return pd.DataFrame(rows)


def evaluate_regime_candidates(
    metrics: pd.DataFrame,
    episodes: pd.DataFrame,
    fold_names: list[str],
) -> dict[str, Any]:
    """按研究前冻结的门槛识别值得另开实验的状态。"""
    result: dict[str, Any] = {}
    for regime in REGIME_ORDER:
        full_rows = metrics[
            (metrics["period"] == "full")
            & (metrics["regime"] == regime)
        ]
        fold_rows = metrics[
            metrics["period"].isin(fold_names)
            & (metrics["regime"] == regime)
        ]
        meaningful_episodes = episodes[
            (episodes["regime"] == regime) & (episodes["days"] >= 5)
        ]
        full = full_rows.iloc[0] if not full_rows.empty else None
        checks = {
            "at_least_120_days": bool(
                full is not None and int(full["days"]) >= 120
            ),
            "positive_satellite_return": bool(
                full is not None
                and float(full["satellite_annualized_return"]) > 0
            ),
            "satellite_sharpe_above_05": bool(
                full is not None
                and float(full["satellite_sharpe"]) > 0.5
            ),
            "satellite_beats_core": bool(
                full is not None
                and float(full["satellite_annual_lift_vs_core"]) > 0
            ),
            "conditional_drawdown_within_25pct": bool(
                full is not None
                and float(full["satellite_max_drawdown"]) >= -0.25
            ),
            "all_folds_positive": bool(
                len(fold_rows) == len(fold_names)
                and (fold_rows["satellite_total_return"] > 0).all()
            ),
            "episode_breadth": bool(
                len(meaningful_episodes) >= 5
                and (
                    meaningful_episodes["satellite_return"] > 0
                ).mean()
                >= 0.55
            ),
        }
        result[regime] = {
            "passed": all(checks.values()),
            "checks": checks,
            "meaningful_episode_count": len(meaningful_episodes),
            "positive_episode_rate": (
                float(
                    (meaningful_episodes["satellite_return"] > 0).mean()
                )
                if not meaningful_episodes.empty
                else 0.0
            ),
        }
    return result


def metric_summary(returns: pd.Series) -> dict[str, float]:
    """把同一状态的离散交易日拼接成条件收益路径。"""
    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    if values.empty:
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "max_drawdown": 0.0,
            "volatility": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
        }
    nav = (1.0 + values).cumprod()
    annualized = float(nav.iloc[-1] ** (252.0 / len(values)) - 1.0)
    drawdown = nav / nav.cummax() - 1.0
    volatility = float(values.std(ddof=1) * math.sqrt(252))
    return {
        "total_return": float(nav.iloc[-1] - 1.0),
        "annualized_return": annualized,
        "max_drawdown": float(drawdown.min()),
        "volatility": volatility,
        "sharpe": (
            float(values.mean() / values.std(ddof=1) * math.sqrt(252))
            if len(values) > 1 and float(values.std(ddof=1)) > 0
            else 0.0
        ),
        "win_rate": float((values > 0).mean()),
    }


def _prefix(prefix: str, values: dict[str, float]) -> dict[str, float]:
    return {f"{prefix}_{key}": value for key, value in values.items()}


def _total_return(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    return float((1.0 + values).prod() - 1.0) if not values.empty else 0.0
