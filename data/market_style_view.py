"""大小盘风格指数只读视图。

中证2000作为小市值/微盘风格代理，沪深300作为大盘风格代理。两者均为
指数原始点位，不适用股票或 ETF 的复权规则。该模块只读取标准基准缓存，
不负责联网更新，也不参与策略信号和仓位计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class MarketStyleDefinition:
    """定义页面展示的风格代理指数。"""

    style_id: str
    name: str
    symbol: str
    proxy_name: str


MARKET_STYLE_DEFINITIONS = (
    MarketStyleDefinition("micro_cap", "微盘风格", "932000.CSI", "中证2000"),
    MarketStyleDefinition("large_cap", "大盘风格", "000300.SH", "沪深300"),
)
MARKET_STYLE_INDEX_SYMBOLS = tuple(item.symbol for item in MARKET_STYLE_DEFINITIONS)
MA_WINDOWS = (5, 10, 20, 60)


def load_market_style_overview(path: str | Path, limit: int = 240) -> dict[str, Any]:
    """从基准 DuckDB 生成大小盘 K 线、均线和相对强弱视图。"""
    database_path = Path(path)
    safe_limit = max(60, min(int(limit), 1000))
    if not database_path.exists():
        return _empty_overview("风格指数缓存不存在")

    frame = _load_index_rows(database_path)
    if frame.empty:
        return _empty_overview("风格指数缓存暂无数据")

    style_payloads: list[dict[str, Any]] = []
    close_series: dict[str, pd.Series] = {}
    for definition in MARKET_STYLE_DEFINITIONS:
        style_frame = _prepare_style_frame(frame, definition.symbol)
        if style_frame.empty:
            continue
        close_series[definition.style_id] = style_frame.set_index("trade_date")["close"]
        style_payloads.append(_style_payload(definition, style_frame, safe_limit))

    available_ids = {item["style_id"] for item in style_payloads}
    status = "READY" if len(available_ids) == len(MARKET_STYLE_DEFINITIONS) else "PARTIAL"
    as_of = _comparable_as_of(style_payloads)
    relative = _build_relative_strength(close_series, safe_limit)
    return {
        "data_status": status,
        "as_of": as_of,
        "adjust_policy": "index_raw",
        "styles": style_payloads,
        "relative_strength": relative,
    }


def _load_index_rows(path: Path) -> pd.DataFrame:
    """只读取注册的风格指数，避免把无关基准加载进 API。"""
    import duckdb

    placeholders = ", ".join("?" for _ in MARKET_STYLE_INDEX_SYMBOLS)
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            return con.execute(
                f"""
                SELECT ts_code, trade_date, open, high, low, close, pct_chg
                FROM index_daily
                WHERE ts_code IN ({placeholders})
                ORDER BY ts_code, trade_date
                """,
                list(MARKET_STYLE_INDEX_SYMBOLS),
            ).fetchdf()
    except Exception:
        return pd.DataFrame()


def _prepare_style_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """标准化指数行情并计算仅依赖历史数据的移动均线。"""
    result = frame.loc[frame["ts_code"] == symbol].copy()
    if result.empty:
        return result
    result["trade_date"] = result["trade_date"].astype(str)
    numeric_columns = ["open", "high", "low", "close", "pct_chg"]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=["open", "high", "low", "close"])
    result = result.loc[(result[["open", "high", "low", "close"]] > 0).all(axis=1)]
    result = result.drop_duplicates("trade_date", keep="last").sort_values("trade_date")
    for window in MA_WINDOWS:
        # rolling 默认只看当前及过去行，避免观测层引入未来数据。
        result[f"ma{window}"] = result["close"].rolling(window, min_periods=window).mean()
    return result.reset_index(drop=True)


def _style_payload(
    definition: MarketStyleDefinition,
    frame: pd.DataFrame,
    limit: int,
) -> dict[str, Any]:
    """把单个风格指数转换成前端稳定契约。"""
    latest = frame.iloc[-1]
    bars = frame.tail(limit)
    return {
        "style_id": definition.style_id,
        "name": definition.name,
        "symbol": definition.symbol,
        "proxy_name": definition.proxy_name,
        "bars": [_bar_record(row) for _, row in bars.iterrows()],
        "summary": {
            "trade_date": str(latest["trade_date"]),
            "close": float(latest["close"]),
            "return_20": _period_return(frame["close"], 20),
            "return_60": _period_return(frame["close"], 60),
            "distance_ma20": _distance_to_ma(latest, "ma20"),
            "distance_ma60": _distance_to_ma(latest, "ma60"),
            "trend_state": _classify_trend(latest),
        },
    }


def _bar_record(row: pd.Series) -> dict[str, Any]:
    """输出 ECharts K 线需要的 OHLC 与均线字段。"""
    record: dict[str, Any] = {
        "trade_date": str(row["trade_date"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "pct_chg": _optional_float(row.get("pct_chg")),
    }
    for window in MA_WINDOWS:
        record[f"ma{window}"] = _optional_float(row.get(f"ma{window}"))
    return record


def _period_return(values: pd.Series, periods: int) -> float | None:
    """计算指定交易日跨度收益，样本不足时明确返回空。"""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) <= periods:
        return None
    base = float(clean.iloc[-periods - 1])
    return float(clean.iloc[-1] / base - 1.0) if base > 0 else None


def _distance_to_ma(latest: pd.Series, column: str) -> float | None:
    value = _optional_float(latest.get(column))
    close = float(latest["close"])
    return close / value - 1.0 if value is not None and value > 0 else None


def _classify_trend(latest: pd.Series) -> str:
    """按价格、MA20、MA60的位置给出直观趋势状态。"""
    close = float(latest["close"])
    ma20 = _optional_float(latest.get("ma20"))
    ma60 = _optional_float(latest.get("ma60"))
    if ma20 is None or ma60 is None:
        return "INSUFFICIENT"
    if close > ma20 > ma60:
        return "UP"
    if close < ma20 < ma60:
        return "DOWN"
    if close > ma20:
        return "REBOUND"
    return "WEAK"


def _build_relative_strength(close_series: dict[str, pd.Series], limit: int) -> dict[str, Any]:
    """计算微盘代理相对大盘代理的价格比值，避免把少跌误判为上涨。"""
    micro = close_series.get("micro_cap")
    large = close_series.get("large_cap")
    if micro is None or large is None:
        return _empty_relative()
    aligned = pd.concat([micro.rename("micro"), large.rename("large")], axis=1, join="inner").dropna()
    if aligned.empty:
        return _empty_relative()
    ratio = aligned["micro"] / aligned["large"]
    normalized = ratio / float(ratio.iloc[0])
    spread_20 = _period_return(ratio, 20)
    state = _classify_relative(spread_20)
    records = [
        {"trade_date": str(trade_date), "relative_nav": float(value)}
        for trade_date, value in normalized.tail(limit).items()
    ]
    return {
        "state": state,
        "spread_20": spread_20,
        "reference_threshold": 0.03,
        "series": records,
    }


def _classify_relative(spread_20: float | None) -> str:
    if spread_20 is None:
        return "UNKNOWN"
    if spread_20 >= 0.03:
        return "MICRO_STRONG"
    if spread_20 <= -0.03:
        return "LARGE_STRONG"
    return "BALANCED"


def _comparable_as_of(styles: list[dict[str, Any]]) -> str:
    dates = [str(item["summary"]["trade_date"]) for item in styles]
    return min(dates) if dates else ""


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _empty_relative() -> dict[str, Any]:
    return {"state": "UNKNOWN", "spread_20": None, "reference_threshold": 0.03, "series": []}


def _empty_overview(message: str) -> dict[str, Any]:
    return {
        "data_status": "MISSING",
        "as_of": "",
        "adjust_policy": "index_raw",
        "message": message,
        "styles": [],
        "relative_strength": _empty_relative(),
    }
