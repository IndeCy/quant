"""游资涨跌停缓存更新流水线。"""

from __future__ import annotations

from typing import Any

import duckdb

from data.tushare_limit_incremental import LimitListClient, LimitListDuckDBStore, TushareLimitClient, update_limit_list_range
from runtime.paths import RuntimePaths


def resolve_hot_money_cache_dates(paths: RuntimePaths, updated_dates: list[str]) -> list[str]:
    """确定本轮需要同步涨跌停缓存的交易日。"""
    dates = sorted({str(item) for item in updated_dates if str(item).strip()})
    if dates or paths.limit_list_increment_path.exists():
        return dates
    latest = _latest_live_market_date(paths)
    return [] if latest is None else [latest]


def update_hot_money_limit_cache(
    paths: RuntimePaths,
    trade_dates: list[str],
    client: LimitListClient | None = None,
) -> dict[str, Any]:
    """把每日涨跌停列表写入统一本地缓存，供研究页只读展示。"""
    dates = sorted({str(item) for item in trade_dates if str(item).strip()})
    if not dates:
        return {"updated_dates": [], "rows_written": 0, "cache_path": str(paths.limit_list_increment_path)}
    paths.ensure_directories()
    store = LimitListDuckDBStore(paths.limit_list_increment_path)
    result = update_limit_list_range(store, client or TushareLimitClient(), dates)
    return {**result, "cache_path": str(paths.limit_list_increment_path)}


def _latest_live_market_date(paths: RuntimePaths) -> str | None:
    if not paths.live_market_increment_path.exists():
        return None
    with duckdb.connect(str(paths.live_market_increment_path), read_only=True) as con:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "daily" not in tables:
            return None
        value = con.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    return str(value) if value else None
