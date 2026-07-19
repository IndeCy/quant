"""大小盘风格观测数据视图测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data.market_style_view import load_market_style_overview
from data.tushare_benchmark_incremental import BenchmarkIncrementalStore, MARKET_COLUMNS


def _index_rows(symbol: str, closes: list[float], dates: pd.DatetimeIndex) -> pd.DataFrame:
    """构造带完整 OHLC 的指数日线，便于核对 K 线和均线。"""
    rows = []
    for trade_date, close in zip(dates, closes, strict=True):
        rows.append(
            {
                "ts_code": symbol,
                "trade_date": trade_date.strftime("%Y%m%d"),
                "open": close - 0.4,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "pre_close": close - 0.5,
                "change": 0.5,
                "pct_chg": 0.5,
                "vol": 1000.0,
                "amount": 10000.0,
            }
        )
    return pd.DataFrame(rows, columns=MARKET_COLUMNS)


def test_market_style_view_builds_kline_ma_and_relative_strength(tmp_path: Path) -> None:
    """风格视图应输出真实 K 线、历史均线和20日相对强弱。"""
    path = tmp_path / "benchmark.duckdb"
    store = BenchmarkIncrementalStore(path)
    dates = pd.bdate_range("2026-01-05", periods=70)
    micro_closes = [100.0 + index * 1.2 for index in range(len(dates))]
    large_closes = [100.0 + index * 0.2 for index in range(len(dates))]
    store.upsert_index(_index_rows("932000.CSI", micro_closes, dates))
    store.upsert_index(_index_rows("000300.SH", large_closes, dates))

    overview = load_market_style_overview(path, limit=60)

    assert overview["data_status"] == "READY"
    assert overview["as_of"] == dates[-1].strftime("%Y%m%d")
    assert [item["style_id"] for item in overview["styles"]] == ["micro_cap", "large_cap"]
    micro = overview["styles"][0]
    assert len(micro["bars"]) == 60
    assert micro["bars"][-1]["close"] == micro_closes[-1]
    assert micro["bars"][-1]["ma5"] == pytest.approx(sum(micro_closes[-5:]) / 5)
    assert micro["bars"][-1]["ma60"] == pytest.approx(sum(micro_closes[-60:]) / 60)
    assert micro["summary"]["return_20"] > overview["styles"][1]["summary"]["return_20"]
    assert overview["relative_strength"]["state"] == "MICRO_STRONG"
    assert overview["relative_strength"]["spread_20"] > 0.03


def test_market_style_view_reports_missing_data_without_placeholder_curve(tmp_path: Path) -> None:
    """缓存不存在时必须明确缺数，不能用零值伪造走势。"""
    overview = load_market_style_overview(tmp_path / "missing.duckdb", limit=120)

    assert overview["data_status"] == "MISSING"
    assert overview["as_of"] == ""
    assert overview["styles"] == []
    assert overview["relative_strength"]["state"] == "UNKNOWN"
