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
    return {
        "status": "READY",
        "message": "已生成最新游资主线与龙头识别",
        "cache_path": str(path),
        "latest_trade_date": latest,
        "mainlines": latest_sector[latest_sector["is_mainline"]].to_dict("records"),
        "leaders": latest_leader[latest_leader["role"].isin(["LEADER", "SECONDARY_LEADER"])].to_dict("records"),
    }


def _read_limit_rows(path: Path) -> pd.DataFrame:
    """只读本地缓存，页面请求不触发外部数据更新。"""
    with duckdb.connect(str(path), read_only=True) as con:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "limit_list_daily" not in tables:
            return pd.DataFrame()
        return con.execute("SELECT * FROM limit_list_daily ORDER BY trade_date, ts_code").fetchdf()


def _empty_view(status: str, message: str) -> dict[str, object]:
    return {
        "status": status,
        "message": message,
        "cache_path": "",
        "latest_trade_date": "",
        "mainlines": [],
        "leaders": [],
    }
