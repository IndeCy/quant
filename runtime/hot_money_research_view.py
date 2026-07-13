"""游资主线龙头研究视图聚合。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from runtime.hot_money_leader import build_leader_stock_daily
from runtime.hot_money_sector import build_sector_momentum_daily
from runtime.hot_money_sector_map import load_hot_money_sector_map


def build_hot_money_research_view(
    cache_path: str | Path,
    sector_map: pd.DataFrame | None = None,
    concept_path: str | Path | None = None,
    industry_path: str | Path | None = None,
) -> dict[str, object]:
    """从本地涨跌停缓存生成前端可展示的最新主线龙头摘要。"""
    path = Path(cache_path)
    if not path.exists():
        return _empty_view("MISSING_CACHE", f"未找到涨跌停缓存: {path}")
    limit_rows = _read_limit_rows(path)
    if limit_rows.empty:
        return _empty_view("NO_DATA", "涨跌停缓存为空")
    if sector_map is None and concept_path is not None and industry_path is not None:
        sector_map = load_hot_money_sector_map(concept_path, industry_path)
    sector = build_sector_momentum_daily(limit_rows, sector_map)
    leader = build_leader_stock_daily(limit_rows, sector, sector_map)
    if sector.empty:
        return _empty_view("NO_LIMIT_UP", "缓存中没有涨停样本")
    latest = str(sector["trade_date"].max())
    latest_sector = sector[sector["trade_date"].astype(str).eq(latest)].sort_values("rank")
    latest_leader = leader[leader["trade_date"].astype(str).eq(latest)].sort_values(
        ["sector_name", "role", "leader_score"],
        ascending=[True, True, False],
    )
    latest_limit_ups = _build_sector_limit_ups(limit_rows, sector_map, latest, latest_leader)
    return {
        "status": "READY",
        "message": "已生成最新游资主线与龙头识别",
        "cache_path": str(path),
        "latest_trade_date": latest,
        "mainlines": latest_sector[latest_sector["is_mainline"]].to_dict("records"),
        "leaders": latest_leader[latest_leader["role"].isin(["LEADER", "SECONDARY_LEADER"])].to_dict("records"),
        "sector_limit_ups": latest_limit_ups.to_dict("records"),
    }


def _read_limit_rows(path: Path) -> pd.DataFrame:
    """只读本地缓存，页面请求不触发外部数据更新。"""
    with duckdb.connect(str(path), read_only=True) as con:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "limit_list_daily" not in tables:
            return pd.DataFrame()
        return con.execute("SELECT * FROM limit_list_daily ORDER BY trade_date, ts_code").fetchdf()


def _build_sector_limit_ups(
    limit_rows: pd.DataFrame,
    sector_map: pd.DataFrame | None,
    latest: str,
    latest_leader: pd.DataFrame,
) -> pd.DataFrame:
    """生成按板块展开的最新涨停票明细，供前端点击主线后查看。"""
    latest_rows = limit_rows[
        limit_rows["trade_date"].astype(str).eq(latest)
        & limit_rows["limit_type"].astype(str).eq("U")
    ].copy()
    if latest_rows.empty:
        return pd.DataFrame()
    if sector_map is None or sector_map.empty:
        latest_rows["sector_name"] = "UNKNOWN"
    else:
        mapping = sector_map[["ts_code", "sector_name"]].drop_duplicates(["ts_code", "sector_name"])
        latest_rows = latest_rows.merge(mapping, on="ts_code", how="left")
        latest_rows["sector_name"] = latest_rows["sector_name"].fillna("UNKNOWN")
    role_cols = ["trade_date", "sector_name", "ts_code", "role", "leader_score", "limit_streak", "amount_share", "reason"]
    details = latest_rows.merge(latest_leader[role_cols], on=["trade_date", "sector_name", "ts_code"], how="left")
    details["role"] = details["role"].fillna("FILTERED")
    details["leader_score"] = details["leader_score"].fillna(0.0)
    details["limit_streak"] = details["limit_streak"].fillna(0).astype(int)
    details["amount_share"] = details["amount_share"].fillna(0.0)
    details["reason"] = details["reason"].fillna("FILTERED: 非主线或强度不足")
    columns = [
        "trade_date",
        "sector_name",
        "ts_code",
        "name",
        "close",
        "pct_chg",
        "amount",
        "fd_amount",
        "first_time",
        "last_time",
        "open_times",
        "role",
        "leader_score",
        "limit_streak",
        "amount_share",
        "reason",
    ]
    return details.sort_values(["sector_name", "role", "leader_score", "amount"], ascending=[True, True, False, False])[columns]


def _empty_view(status: str, message: str) -> dict[str, object]:
    return {
        "status": status,
        "message": message,
        "cache_path": "",
        "latest_trade_date": "",
        "mainlines": [],
        "leaders": [],
        "sector_limit_ups": [],
    }
