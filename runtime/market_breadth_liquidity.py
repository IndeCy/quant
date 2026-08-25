"""全市场宽度与流动性指标计算。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_breadth_liquidity_frame(
    daily: pd.DataFrame,
    ma_windows: tuple[int, ...] = (20, 60, 120),
    high_low_window: int = 20,
) -> pd.DataFrame:
    """把全A日线压缩成日频市场宽度和流动性指标。"""
    if daily.empty:
        return pd.DataFrame()
    frame = daily.copy()
    frame["trade_date"] = frame["trade_date"].astype(str)
    frame["ts_code"] = frame["ts_code"].astype(str)
    for column in ["close", "pre_close", "vol", "amount"]:
        frame[column] = pd.to_numeric(frame.get(column, 0.0), errors="coerce").fillna(0.0)
    frame = frame.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    frame["daily_return"] = _daily_return(frame)
    for window in ma_windows:
        rolling_ma = frame.groupby("ts_code")["close"].transform(lambda item: item.rolling(window, min_periods=1).mean())
        frame[f"ma{window}_above"] = frame["close"] >= rolling_ma
    rolling_high = frame.groupby("ts_code")["close"].transform(lambda item: item.rolling(high_low_window, min_periods=1).max())
    rolling_low = frame.groupby("ts_code")["close"].transform(lambda item: item.rolling(high_low_window, min_periods=1).min())
    frame["new_high"] = frame["close"] >= rolling_high
    frame["new_low"] = frame["close"] <= rolling_low
    grouped = frame.groupby("trade_date", sort=True)
    result = grouped.agg(
        breadth_up_count=("daily_return", lambda item: int((item > 0).sum())),
        breadth_down_count=("daily_return", lambda item: int((item < 0).sum())),
        breadth_flat_count=("daily_return", lambda item: int((item == 0).sum())),
        equal_weight_return=("daily_return", "mean"),
        median_return=("daily_return", "median"),
        market_amount=("amount", "sum"),
        zero_volume_ratio=("vol", lambda item: float((item <= 0).mean())),
        new_high_20_count=("new_high", "sum"),
        new_low_20_count=("new_low", "sum"),
    )
    for window in ma_windows:
        source = f"ma{window}_above"
        target = f"ma{window}_above_ratio"
        result[target] = grouped[source].mean()
    result["amount_ma20"] = result["market_amount"].rolling(20, min_periods=1).mean()
    result["amount_ratio_20"] = result["market_amount"] / result["amount_ma20"].replace(0, pd.NA)
    result["low_amount_ratio"] = grouped.apply(_low_amount_ratio, include_groups=False)
    result = result.reset_index()
    return result.fillna(0.0)


def load_recent_daily_bars(base_path: Path, increment_path: Path, end_date: str, lookback_days: int = 180) -> pd.DataFrame:
    """从基线库和增量库合并读取最近全A日线。"""
    if not base_path.exists() or not increment_path.exists():
        return pd.DataFrame()
    from data.live_market_view import open_live_market_connection

    con = open_live_market_connection(
        base_path,
        increment_path,
        lookback_start="20000101",
        as_of_date=end_date,
    )
    try:
        dates = con.execute(
            """
            SELECT DISTINCT trade_date
            FROM daily
            WHERE trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [end_date, int(lookback_days)],
        ).fetchdf()["trade_date"].astype(str).tolist()
        if not dates:
            return pd.DataFrame()
        start_date = min(dates)
        return con.execute(
            """
            SELECT ts_code, trade_date, close, pre_close, vol, amount
            FROM daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY ts_code, trade_date
            """,
            [start_date, end_date],
        ).fetchdf()
    finally:
        con.close()


def _daily_return(frame: pd.DataFrame) -> pd.Series:
    """优先用 pre_close 计算单日收益，异常价格置为0。"""
    base = frame["pre_close"].where(frame["pre_close"] > 0)
    result = frame["close"] / base - 1.0
    return result.replace([float("inf"), float("-inf")], 0.0).fillna(0.0)


def _low_amount_ratio(group: pd.DataFrame) -> float:
    """计算当日成交额最低20%股票占比，空组返回0。"""
    if group.empty:
        return 0.0
    amount = pd.to_numeric(group["amount"], errors="coerce").fillna(0.0)
    threshold = amount.quantile(0.2)
    return float((amount <= threshold).mean())
