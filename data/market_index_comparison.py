"""多策略净值图使用的市场指数只读对比序列。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class MarketIndexDefinition:
    """允许展示在策略对比图中的指数。"""

    symbol: str
    name: str


MARKET_INDEX_DEFINITIONS = (
    MarketIndexDefinition("000001.SH", "上证指数"),
    MarketIndexDefinition("000300.SH", "沪深300"),
)
MARKET_INDEX_SYMBOLS = tuple(item.symbol for item in MARKET_INDEX_DEFINITIONS)


def load_market_index_comparison(path: str | Path, limit: int = 5000) -> dict[str, Any]:
    """读取原始指数收盘价并转换为前端可再次按窗口归一的净值序列。"""
    database_path = Path(path)
    safe_limit = max(2, min(int(limit), 5000))
    if not database_path.exists():
        return _empty_result("指数基准缓存不存在")

    frame = _load_index_rows(database_path)
    if frame.empty:
        return _empty_result("指数基准缓存暂无数据")

    indices: list[dict[str, Any]] = []
    for definition in MARKET_INDEX_DEFINITIONS:
        rows = _prepare_index_frame(frame, definition.symbol).tail(safe_limit)
        if rows.empty:
            continue
        first_close = float(rows.iloc[0]["close"])
        indices.append(
            {
                "symbol": definition.symbol,
                "name": definition.name,
                "points": [
                    {
                        "trade_date": str(row["trade_date"]),
                        "nav": float(row["close"]) / first_close,
                    }
                    for _, row in rows.iterrows()
                ],
            }
        )

    status = "READY" if len(indices) == len(MARKET_INDEX_DEFINITIONS) else "PARTIAL"
    as_of_dates = [str(item["points"][-1]["trade_date"]) for item in indices]
    return {
        "data_status": status,
        "as_of": min(as_of_dates) if as_of_dates else "",
        "adjust_policy": "index_raw",
        "indices": indices,
    }


def _load_index_rows(path: Path) -> pd.DataFrame:
    """只读取允许展示的两个指数，避免 API 暴露任意表查询。"""
    import duckdb

    placeholders = ", ".join("?" for _ in MARKET_INDEX_SYMBOLS)
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            return con.execute(
                f"""
                SELECT ts_code, trade_date, close
                FROM index_daily
                WHERE ts_code IN ({placeholders})
                ORDER BY ts_code, trade_date
                """,
                list(MARKET_INDEX_SYMBOLS),
            ).fetchdf()
    except Exception:
        return pd.DataFrame()


def _prepare_index_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """清洗单指数日期和收盘价。"""
    result = frame.loc[frame["ts_code"] == symbol, ["trade_date", "close"]].copy()
    if result.empty:
        return result
    result["trade_date"] = result["trade_date"].astype(str)
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result = result.dropna(subset=["close"])
    result = result.loc[result["close"] > 0]
    return result.drop_duplicates("trade_date", keep="last").sort_values("trade_date").reset_index(drop=True)


def _empty_result(message: str) -> dict[str, Any]:
    return {
        "data_status": "MISSING",
        "as_of": "",
        "adjust_policy": "index_raw",
        "message": message,
        "indices": [],
    }
