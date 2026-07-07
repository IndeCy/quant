"""游资主线板块强度识别。"""

from __future__ import annotations

import pandas as pd

SECTOR_COLUMNS = [
    "trade_date",
    "sector_name",
    "limit_up_count",
    "limit_amount",
    "leader_ts_code",
    "leader_name",
    "leader_score",
    "consistency_score",
    "uniqueness_score",
    "sector_score",
    "rank",
    "is_mainline",
    "reason",
]


def build_sector_momentum_daily(
    limit_rows: pd.DataFrame,
    sector_map: pd.DataFrame | None = None,
    max_mainlines: int = 3,
) -> pd.DataFrame:
    """按交易日识别 1 到 3 条短线主线板块。"""
    if limit_rows.empty:
        return pd.DataFrame(columns=SECTOR_COLUMNS)
    rows = _attach_sector(limit_rows, sector_map)
    rows = rows[rows["limit_type"].astype(str).eq("U")].copy()
    if rows.empty:
        return pd.DataFrame(columns=SECTOR_COLUMNS)
    outputs = [_score_one_day(str(trade_date), daily, max_mainlines) for trade_date, daily in rows.groupby("trade_date", sort=True)]
    return pd.concat(outputs, ignore_index=True)[SECTOR_COLUMNS]


def _attach_sector(limit_rows: pd.DataFrame, sector_map: pd.DataFrame | None) -> pd.DataFrame:
    """挂接板块映射，缺失时归入 UNKNOWN，避免错误制造主线。"""
    rows = limit_rows.copy()
    if sector_map is None or sector_map.empty:
        rows["sector_name"] = "UNKNOWN"
        return rows
    mapping = sector_map[["ts_code", "sector_name"]].drop_duplicates("ts_code")
    merged = rows.merge(mapping, on="ts_code", how="left")
    merged["sector_name"] = merged["sector_name"].fillna("UNKNOWN")
    return merged


def _score_one_day(trade_date: str, daily: pd.DataFrame, max_mainlines: int) -> pd.DataFrame:
    grouped = daily.groupby("sector_name", dropna=False)
    sector = grouped.agg(
        limit_up_count=("ts_code", "nunique"),
        limit_amount=("amount", "sum"),
        avg_open_times=("open_times", "mean"),
        avg_pct_chg=("pct_chg", "mean"),
    ).reset_index()
    sector["leader_ts_code"] = grouped.apply(_leader_code, include_groups=False).to_numpy()
    sector["leader_name"] = grouped.apply(_leader_name, include_groups=False).to_numpy()
    sector["leader_score"] = (_percent_rank(sector["limit_amount"]) * 60 + _percent_rank(sector["avg_pct_chg"]) * 40).round(2)
    sector["consistency_score"] = ((1.0 - sector["avg_open_times"].fillna(0).clip(0, 5) / 5.0) * 100).round(2)
    count_score = _percent_rank(sector["limit_up_count"]) * 100
    amount_score = _percent_rank(sector["limit_amount"]) * 100
    sector["sector_score"] = (0.35 * count_score + 0.25 * amount_score + 0.25 * sector["leader_score"] + 0.15 * sector["consistency_score"]).round(2)
    sector = sector.sort_values(["sector_score", "limit_up_count", "limit_amount"], ascending=False).reset_index(drop=True)
    sector["rank"] = sector.index + 1
    sector["uniqueness_score"] = _uniqueness_scores(sector["sector_score"])
    mainline_count = _mainline_count(sector, max_mainlines)
    sector["is_mainline"] = sector["rank"].le(mainline_count)
    sector["trade_date"] = trade_date
    sector["reason"] = sector.apply(_sector_reason, axis=1)
    return sector


def _leader_code(frame: pd.DataFrame) -> str:
    row = frame.sort_values(["amount", "pct_chg"], ascending=False).iloc[0]
    return str(row["ts_code"])


def _leader_name(frame: pd.DataFrame) -> str:
    row = frame.sort_values(["amount", "pct_chg"], ascending=False).iloc[0]
    return str(row.get("name", ""))


def _percent_rank(values: pd.Series) -> pd.Series:
    """横截面分位数，单板块时给满分，避免除零。"""
    if len(values) == 1:
        return pd.Series([1.0], index=values.index)
    return values.rank(method="average", pct=True).fillna(0.0)


def _uniqueness_scores(scores: pd.Series) -> pd.Series:
    if scores.empty:
        return scores
    top = float(scores.iloc[0])
    return ((top - scores) / max(top, 1.0) * 100).round(2)


def _mainline_count(sector: pd.DataFrame, max_mainlines: int) -> int:
    if sector.empty:
        return 0
    if len(sector) == 1:
        return 1
    gap = float(sector.iloc[0]["sector_score"] - sector.iloc[1]["sector_score"])
    if gap >= 40:
        return 1
    eligible = sector[(sector["rank"].eq(1)) | (sector["sector_score"] >= 45)]
    return max(1, min(max_mainlines, len(eligible)))


def _sector_reason(row: pd.Series) -> str:
    role = "主线" if bool(row["is_mainline"]) else "观察"
    return f"{role}: 涨停{int(row['limit_up_count'])}家，成交额{float(row['limit_amount']):.2f}，一致性{float(row['consistency_score']):.1f}"
