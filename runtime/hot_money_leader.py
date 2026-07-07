"""游资主线龙头识别。"""

from __future__ import annotations

import pandas as pd

LEADER_COLUMNS = [
    "trade_date",
    "sector_name",
    "ts_code",
    "name",
    "role",
    "leader_score",
    "limit_streak",
    "amount_share",
    "open_times",
    "reason",
]


def build_leader_stock_daily(
    limit_rows: pd.DataFrame,
    sector_momentum: pd.DataFrame,
    sector_map: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """识别主线板块内唯一龙头、次级龙头和过滤对象。"""
    if limit_rows.empty:
        return pd.DataFrame(columns=LEADER_COLUMNS)
    rows = _attach_sector(limit_rows, sector_map)
    rows = rows.sort_values(["ts_code", "trade_date"]).copy()
    rows["limit_streak"] = _limit_streak(rows)
    rows = rows[rows["limit_type"].astype(str).eq("U")].copy()
    if rows.empty:
        return pd.DataFrame(columns=LEADER_COLUMNS)
    mainline_keys = _mainline_keys(sector_momentum)
    outputs = [
        _score_sector(str(trade_date), str(sector_name), daily_sector, mainline_keys)
        for (trade_date, sector_name), daily_sector in rows.groupby(["trade_date", "sector_name"], sort=True)
    ]
    return pd.concat(outputs, ignore_index=True)[LEADER_COLUMNS]


def _attach_sector(limit_rows: pd.DataFrame, sector_map: pd.DataFrame | None) -> pd.DataFrame:
    rows = limit_rows.copy()
    if sector_map is None or sector_map.empty:
        rows["sector_name"] = "UNKNOWN"
        return rows
    mapping = sector_map[["ts_code", "sector_name"]].drop_duplicates("ts_code")
    merged = rows.merge(mapping, on="ts_code", how="left")
    merged["sector_name"] = merged["sector_name"].fillna("UNKNOWN")
    return merged


def _limit_streak(rows: pd.DataFrame) -> pd.Series:
    """按股票时间序列计算连续涨停天数。"""
    streaks: list[int] = []
    current_code = ""
    current_streak = 0
    for row in rows.itertuples(index=False):
        if str(row.ts_code) != current_code:
            current_code = str(row.ts_code)
            current_streak = 0
        current_streak = current_streak + 1 if str(row.limit_type) == "U" else 0
        streaks.append(current_streak)
    return pd.Series(streaks, index=rows.index)


def _mainline_keys(sector_momentum: pd.DataFrame) -> set[tuple[str, str]]:
    if sector_momentum.empty:
        return set()
    rows = sector_momentum[sector_momentum["is_mainline"].astype(bool)]
    return {(str(row["trade_date"]), str(row["sector_name"])) for _, row in rows.iterrows()}


def _score_sector(
    trade_date: str,
    sector_name: str,
    daily_sector: pd.DataFrame,
    mainline_keys: set[tuple[str, str]],
) -> pd.DataFrame:
    sector_total_amount = max(float(daily_sector["amount"].fillna(0).sum()), 1.0)
    scored = daily_sector.copy()
    scored["amount_share"] = scored["amount"].fillna(0).astype(float) / sector_total_amount
    scored["leader_score"] = (
        scored["limit_streak"].clip(0, 6) / 6 * 35
        + scored["amount_share"].clip(0, 1) * 30
        + (1 - scored["open_times"].fillna(0).clip(0, 5) / 5) * 20
        + scored["pct_chg"].fillna(0).clip(0, 20) / 20 * 15
    ).round(2)
    scored = scored.sort_values(["leader_score", "limit_streak", "amount"], ascending=False).reset_index(drop=True)
    scored["role"] = _assign_roles(scored, (trade_date, sector_name) in mainline_keys)
    scored["trade_date"] = trade_date
    scored["sector_name"] = sector_name
    scored["reason"] = scored.apply(_leader_reason, axis=1)
    return scored


def _assign_roles(scored: pd.DataFrame, is_mainline: bool) -> list[str]:
    roles: list[str] = []
    for index, row in scored.iterrows():
        if not is_mainline:
            roles.append("FILTERED")
        elif index == 0:
            roles.append("LEADER")
        elif index <= 2 and float(row["leader_score"]) >= 35:
            roles.append("SECONDARY_LEADER")
        else:
            roles.append("FILTERED")
    return roles


def _leader_reason(row: pd.Series) -> str:
    return f"{row['role']}: 连板{int(row['limit_streak'])}，成交占比{float(row['amount_share']):.1%}，开板{int(row['open_times'])}次"
