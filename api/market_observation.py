"""大盘观测 API 展示契约。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def attach_market_observation_status(frame: pd.DataFrame, limit_cache_path: Path) -> pd.DataFrame:
    """标记派生数据是否真实存在，避免前端把缺失错误显示为 0。"""
    if frame.empty:
        return frame
    result = frame.copy()
    breadth_columns = ["breadth_up_count", "breadth_down_count", "breadth_flat_count"]
    breadth_total = (
        result.reindex(columns=breadth_columns)
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
        .sum(axis=1)
    )
    result["breadth_data_status"] = breadth_total.gt(0).map({True: "READY", False: "MISSING"})
    cached_dates = _duckdb_distinct_dates(limit_cache_path, "limit_list_daily", "trade_date")
    result["limit_data_status"] = result["trade_date"].astype(str).isin(cached_dates).map(
        {True: "READY", False: "MISSING"}
    )
    return result


def _duckdb_distinct_dates(path: Path, table: str, column: str) -> set[str]:
    """只读取得缓存已有日期；缓存不可用时返回空集合。"""
    if not path.exists():
        return set()
    try:
        import duckdb

        with duckdb.connect(str(path), read_only=True) as con:
            tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
            if table not in tables:
                return set()
            rows = con.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL"
            ).fetchall()
    except Exception:
        return set()
    return {str(row[0]) for row in rows}
