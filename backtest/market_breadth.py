"""
市场宽度快照模块

用于查询和缓存 A 股涨停数、上涨数、下跌数、平盘数等市场情绪指标。
该类数据不是 OHLCV 时间序列，因此使用独立 SQLite 缓存表。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time as time_module
from datetime import datetime, time
from pathlib import Path
from typing import Callable, Dict, Optional

import pandas as pd
import requests


DEFAULT_BREADTH_CACHE_PATH = Path("data/market_breadth.sqlite3")
EASTMONEY_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
LimitUpFetcher = Callable[[str], pd.DataFrame]
SpotFetcher = Callable[[], pd.DataFrame]
MARKET_BREADTH_INDEXES = {
    "上证指数": "1.000001",
    "深证成指": "0.399001",
    "北证50": "0.899050",
}


def _get_json_with_retries(url: str, params: Dict[str, str], headers: Dict[str, str], timeout: int) -> Dict[str, object]:
    """请求东方财富接口，短暂网络抖动时自动重试。"""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request_headers = {"Connection": "close", "Accept": "application/json", **headers}
            response = requests.get(url, params=params, headers=request_headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time_module.sleep(0.3 * (attempt + 1))
    raise RuntimeError(f"东方财富接口请求失败, params={params}: {last_error}")


class MarketBreadthCache:
    """市场宽度快照本地缓存。"""

    def __init__(self, db_path: Path | str = DEFAULT_BREADTH_CACHE_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        """关闭 SQLite 连接。"""
        self.conn.close()

    def _init_schema(self) -> None:
        """初始化市场宽度快照表。"""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_breadth_snapshot (
              id integer PRIMARY KEY AUTOINCREMENT,
              date varchar(8) NOT NULL DEFAULT '',
              provider varchar(50) NOT NULL DEFAULT '',
              limit_up_count integer NOT NULL DEFAULT 0,
              up_count integer NOT NULL DEFAULT 0,
              down_count integer NOT NULL DEFAULT 0,
              flat_count integer NOT NULL DEFAULT 0,
              fetched_at datetime NOT NULL,
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(date, provider)
            );

            CREATE INDEX IF NOT EXISTS idx_market_breadth_date
            ON market_breadth_snapshot(date, provider);
            """
        )
        self.conn.commit()

    def read_snapshot(self, date_str: str, provider: str = "eastmoney") -> Optional[Dict[str, object]]:
        """读取某天某数据源的市场宽度快照。"""
        row = self.conn.execute(
            """
            SELECT date, provider, limit_up_count, up_count, down_count, flat_count, fetched_at
            FROM market_breadth_snapshot
            WHERE date = ?
              AND provider = ?
            """,
            (date_str, provider),
        ).fetchone()
        if row is None:
            return None
        return {
            "date": row["date"],
            "涨停数": int(row["limit_up_count"]),
            "上涨数": int(row["up_count"]),
            "下跌数": int(row["down_count"]),
            "平盘数": int(row["flat_count"]),
            "provider": row["provider"],
            "fetched_at": row["fetched_at"],
        }

    def save_snapshot(self, snapshot: Dict[str, object], fetched_at: datetime) -> None:
        """写入或更新市场宽度快照。"""
        self.conn.execute(
            """
            INSERT INTO market_breadth_snapshot (
              date, provider, limit_up_count, up_count, down_count, flat_count, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, provider)
            DO UPDATE SET
              limit_up_count = excluded.limit_up_count,
              up_count = excluded.up_count,
              down_count = excluded.down_count,
              flat_count = excluded.flat_count,
              fetched_at = excluded.fetched_at,
              modify_time = CURRENT_TIMESTAMP
            """,
            (
                str(snapshot["date"]),
                str(snapshot.get("provider", "eastmoney")),
                int(snapshot["涨停数"]),
                int(snapshot["上涨数"]),
                int(snapshot["下跌数"]),
                int(snapshot["平盘数"]),
                fetched_at.isoformat(sep=" ", timespec="seconds"),
            ),
        )
        self.conn.commit()


def _is_cache_fresh(snapshot: Dict[str, object], now: datetime, ttl_minutes: int) -> bool:
    """判断缓存是否可复用：收盘后长期有效，盘中按 TTL 判断。"""
    fetched_at = datetime.fromisoformat(str(snapshot["fetched_at"]))
    if fetched_at.time() >= time(15, 0):
        return True
    return (now - fetched_at).total_seconds() <= ttl_minutes * 60


def fetch_eastmoney_limit_up_pool(date_str: str) -> pd.DataFrame:
    """查询东方财富涨停池，用于获得真实涨停数。"""
    url = "https://push2ex.eastmoney.com/getTopicZTPool"
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "pagesize": "10000",
        "sort": "fbt:asc",
        "date": date_str,
    }
    payload = _get_json_with_retries(url, params, {"User-Agent": EASTMONEY_UA}, timeout=15)
    items = (payload.get("data") or {}).get("pool") or []
    return pd.DataFrame(items)


def fetch_eastmoney_a_spot(page_size: int = 100) -> pd.DataFrame:
    """查询东方财富全A实时快照，用于统计上涨、下跌和平盘家数。"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    items = []
    page = 1
    total = None
    while total is None or len(items) < total:
        params = {
            "pn": str(page),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f3",
        }
        payload = _get_json_with_retries(
            url,
            params=params,
            headers={"User-Agent": EASTMONEY_UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=20,
        )
        data = payload.get("data") or {}
        page_items = data.get("diff") or []
        items.extend(page_items)
        total = int(data.get("total") or len(items))
        if not page_items:
            break
        page += 1
    rows = [{"代码": item.get("f12", ""), "名称": item.get("f14", ""), "涨跌幅": float(item.get("f3", 0) or 0)} for item in items]
    return pd.DataFrame(rows)


def fetch_eastmoney_market_breadth() -> pd.DataFrame:
    """查询主要交易所指数中的涨跌平家数字段，汇总为全市场宽度。"""
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    rows = []
    for index_name, secid in MARKET_BREADTH_INDEXES.items():
        payload = _get_json_with_retries(
            url,
            {"secid": secid, "fields": "f113,f114,f115,f57,f58"},
            {"User-Agent": EASTMONEY_UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=15,
        )
        data = payload.get("data") or {}
        rows.append(
            {
                "指数": index_name,
                "上涨数": int(data.get("f113") or 0),
                "下跌数": int(data.get("f114") or 0),
                "平盘数": int(data.get("f115") or 0),
            }
        )
    return pd.DataFrame(rows)


def _calculate_snapshot(date_str: str, limit_up_df: pd.DataFrame, spot_df: pd.DataFrame) -> Dict[str, object]:
    """根据涨停池和全A快照计算市场宽度。"""
    if {"上涨数", "下跌数", "平盘数"}.issubset(spot_df.columns):
        return {
            "date": date_str,
            "涨停数": int(len(limit_up_df)),
            "上涨数": int(pd.to_numeric(spot_df["上涨数"], errors="coerce").fillna(0).sum()),
            "下跌数": int(pd.to_numeric(spot_df["下跌数"], errors="coerce").fillna(0).sum()),
            "平盘数": int(pd.to_numeric(spot_df["平盘数"], errors="coerce").fillna(0).sum()),
            "provider": "eastmoney",
        }
    if "涨跌幅" not in spot_df.columns:
        raise ValueError("全A快照缺少涨跌幅列")
    change_pct = pd.to_numeric(spot_df["涨跌幅"], errors="coerce").fillna(0)
    return {
        "date": date_str,
        "涨停数": int(len(limit_up_df)),
        "上涨数": int((change_pct > 0).sum()),
        "下跌数": int((change_pct < 0).sum()),
        "平盘数": int((change_pct == 0).sum()),
        "provider": "eastmoney",
    }


def get_market_breadth(
    date_str: str,
    cache: Optional[MarketBreadthCache] = None,
    fetch_limit_up: LimitUpFetcher = fetch_eastmoney_limit_up_pool,
    fetch_spot: SpotFetcher = fetch_eastmoney_market_breadth,
    now: Optional[datetime] = None,
    ttl_minutes: int = 15,
    force_refresh: bool = False,
) -> Dict[str, object]:
    """获取市场宽度快照，默认优先读缓存，缓存过期后再请求外部接口。"""
    current_time = now or datetime.now()
    own_cache = cache is None
    cache = cache or MarketBreadthCache()
    try:
        cached = cache.read_snapshot(date_str, provider="eastmoney")
        if cached and not force_refresh and _is_cache_fresh(cached, current_time, ttl_minutes):
            return cached

        snapshot = _calculate_snapshot(date_str, fetch_limit_up(date_str), fetch_spot())
        cache.save_snapshot(snapshot, fetched_at=current_time)
        return snapshot
    finally:
        if own_cache:
            cache.close()


def main() -> None:
    """命令行入口，便于手工查询并写入本地缓存。"""
    parser = argparse.ArgumentParser(description="查询A股市场宽度快照")
    parser.add_argument("date", help="交易日期，格式 YYYYMMDD")
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存并重新请求外部接口")
    args = parser.parse_args()
    snapshot = get_market_breadth(args.date, force_refresh=args.refresh)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
