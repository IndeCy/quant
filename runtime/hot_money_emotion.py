"""游资情绪每日指标聚合。"""

from __future__ import annotations

import pandas as pd


EMOTION_COLUMNS = [
    "trade_date",
    "limit_up_count",
    "limit_down_count",
    "zha_ban_count",
    "open_board_rate",
    "limit_amount",
    "market_amount",
    "market_amount_chg",
]


def build_market_emotion_daily(limit_rows: pd.DataFrame, market_amount: pd.DataFrame | None = None) -> pd.DataFrame:
    """按交易日聚合涨跌停情绪指标，供状态机使用。"""
    if limit_rows.empty:
        return pd.DataFrame(columns=EMOTION_COLUMNS)
    rows = limit_rows.copy()
    rows["limit_type"] = rows["limit_type"].fillna("").astype(str)
    rows["open_times"] = pd.to_numeric(rows.get("open_times", 0), errors="coerce").fillna(0).astype(int)
    rows["amount"] = pd.to_numeric(rows.get("amount", 0.0), errors="coerce").fillna(0.0)
    rows["opened_limit_up"] = ((rows["limit_type"] == "U") & (rows["open_times"] > 0)).astype(int)
    grouped = rows.groupby("trade_date", as_index=False).agg(
        limit_up_count=("limit_type", lambda value: int((value == "U").sum())),
        limit_down_count=("limit_type", lambda value: int((value == "D").sum())),
        zha_ban_count=("limit_type", lambda value: int((value == "Z").sum())),
        opened_limit_up_count=("opened_limit_up", "sum"),
        limit_amount=("amount", "sum"),
    )
    grouped["open_board_rate"] = grouped.apply(
        lambda row: 0.0 if row["limit_up_count"] == 0 else row["opened_limit_up_count"] / row["limit_up_count"],
        axis=1,
    )
    grouped = grouped.drop(columns=["opened_limit_up_count"])
    if market_amount is not None and not market_amount.empty:
        amount = market_amount[["trade_date", "market_amount"]].copy()
        amount["market_amount"] = pd.to_numeric(amount["market_amount"], errors="coerce").fillna(0.0)
        grouped = grouped.merge(amount, on="trade_date", how="left")
        grouped = grouped.sort_values("trade_date")
        grouped["market_amount_chg"] = grouped["market_amount"].pct_change().fillna(0.0)
    else:
        grouped["market_amount"] = 0.0
        grouped["market_amount_chg"] = 0.0
    return grouped[EMOTION_COLUMNS].sort_values("trade_date").reset_index(drop=True)
