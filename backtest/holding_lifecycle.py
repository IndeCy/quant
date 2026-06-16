"""
持仓生命周期分析。

该模块只基于实际成交记录重建持仓生命周期，不使用理论目标权重估算。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class HoldingPeriod:
    """一段连续持仓生命周期。"""

    symbol: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    holding_days: int
    is_open: bool = False


def build_holding_periods(
    trades: list[dict] | pd.DataFrame,
    end_date: str | pd.Timestamp | None = None,
) -> list[HoldingPeriod]:
    """
    从真实成交记录重建每只股票的连续持仓区间。

    只要仓位从 0 变为正数，即开始一个生命周期；期间加减仓但仓位仍为正，
    视为同一段连续持仓；仓位回到 0 时生命周期结束。
    """
    frame = pd.DataFrame(trades)
    if frame.empty:
        return []
    required = {"date", "symbol", "quantity"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"成交记录缺少字段: {sorted(missing)}")

    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values(["date", "symbol"])
    fallback_end = pd.Timestamp(end_date).normalize() if end_date is not None else frame["date"].max()

    periods: list[HoldingPeriod] = []
    positions: dict[str, int] = {}
    starts: dict[str, pd.Timestamp] = {}
    for _, row in frame.iterrows():
        symbol = str(row["symbol"])
        date = pd.Timestamp(row["date"]).normalize()
        quantity = int(row["quantity"])
        previous_position = positions.get(symbol, 0)
        new_position = previous_position + quantity

        if previous_position <= 0 and new_position > 0:
            starts[symbol] = date
        if previous_position > 0 and new_position <= 0:
            start = starts.pop(symbol, date)
            periods.append(
                HoldingPeriod(
                    symbol=symbol,
                    start_date=start,
                    end_date=date,
                    holding_days=max((date - start).days, 0),
                    is_open=False,
                )
            )

        if new_position <= 0:
            positions.pop(symbol, None)
        else:
            positions[symbol] = new_position

    for symbol, quantity in positions.items():
        if quantity <= 0:
            continue
        start = starts.get(symbol, fallback_end)
        periods.append(
            HoldingPeriod(
                symbol=symbol,
                start_date=start,
                end_date=fallback_end,
                holding_days=max((fallback_end - start).days, 0),
                is_open=True,
            )
        )
    return periods


def holding_periods_frame(periods: list[HoldingPeriod]) -> pd.DataFrame:
    """把生命周期列表转为 DataFrame。"""
    return pd.DataFrame(
        [
            {
                "symbol": item.symbol,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "holding_days": item.holding_days,
                "is_open": item.is_open,
            }
            for item in periods
        ]
    )


def holding_distribution(periods: list[HoldingPeriod]) -> dict[str, float]:
    """计算持仓周期分布。"""
    frame = holding_periods_frame(periods)
    if frame.empty:
        return {"lt_1m": 0.0, "m1_3": 0.0, "m3_6": 0.0, "gt_6m": 0.0}
    days = frame["holding_days"]
    total = len(days)
    return {
        "lt_1m": float((days < 30).sum() / total),
        "m1_3": float(((days >= 30) & (days < 90)).sum() / total),
        "m3_6": float(((days >= 90) & (days < 180)).sum() / total),
        "gt_6m": float((days >= 180).sum() / total),
    }


def lifecycle_summary(
    trades: list[dict] | pd.DataFrame,
    end_date: str | pd.Timestamp | None = None,
) -> dict[str, object]:
    """输出生命周期核心指标。"""
    periods = build_holding_periods(trades, end_date=end_date)
    frame = holding_periods_frame(periods)
    if frame.empty:
        distribution = holding_distribution(periods)
        return {
            "average_holding_days": 0.0,
            "median_holding_days": 0.0,
            **distribution,
            "period_count": 0,
            "open_period_count": 0,
        }
    distribution = holding_distribution(periods)
    return {
        "average_holding_days": float(frame["holding_days"].mean()),
        "median_holding_days": float(frame["holding_days"].median()),
        **distribution,
        "period_count": int(len(frame)),
        "open_period_count": int(frame["is_open"].sum()),
    }


def monthly_holding_sets(
    trades: list[dict] | pd.DataFrame,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[pd.Timestamp, set[str]]:
    """按月末重建真实持仓集合。"""
    frame = pd.DataFrame(trades)
    months = pd.date_range(pd.Timestamp(start_date), pd.Timestamp(end_date), freq="ME")
    if frame.empty:
        return {month.normalize(): set() for month in months}

    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values("date")
    positions: dict[str, int] = {}
    result: dict[pd.Timestamp, set[str]] = {}
    trade_index = 0
    rows = frame.to_dict("records")
    for month_end in months:
        month_end = month_end.normalize()
        while trade_index < len(rows) and pd.Timestamp(rows[trade_index]["date"]) <= month_end:
            row = rows[trade_index]
            symbol = str(row["symbol"])
            positions[symbol] = positions.get(symbol, 0) + int(row["quantity"])
            if positions[symbol] <= 0:
                positions.pop(symbol, None)
            trade_index += 1
        result[month_end] = {symbol for symbol, quantity in positions.items() if quantity > 0}
    return result


def rolling_retention(
    trades: list[dict] | pd.DataFrame,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.Series:
    """计算相邻月真实持仓保留率。"""
    holdings = monthly_holding_sets(trades, start_date, end_date)
    values: dict[pd.Timestamp, float] = {}
    previous: set[str] | None = None
    for month, current in holdings.items():
        if previous is None or not previous:
            previous = current
            continue
        values[month] = len(previous & current) / len(previous)
        previous = current
    return pd.Series(values, name="rolling_retention")


def symbol_lifecycle_summary(periods: list[HoldingPeriod]) -> pd.DataFrame:
    """输出每只股票平均持仓时间。"""
    frame = holding_periods_frame(periods)
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "average_holding_days", "period_count", "max_holding_days"])
    summary = (
        frame.groupby("symbol")["holding_days"]
        .agg(average_holding_days="mean", period_count="count", max_holding_days="max")
        .reset_index()
        .sort_values(["average_holding_days", "max_holding_days"], ascending=False)
    )
    return summary
