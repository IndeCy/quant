"""大小盘风格观测 API 测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd

from api.local_server import create_app
from api.service import LocalApiService
from data.tushare_benchmark_incremental import BenchmarkIncrementalStore, MARKET_COLUMNS
from runtime.paths import RuntimePaths


def _seed_index(store: BenchmarkIncrementalStore, symbol: str, offset: float) -> None:
    """写入足够计算 MA60 的指数样本。"""
    rows = []
    for index, trade_date in enumerate(pd.bdate_range("2026-01-05", periods=65)):
        close = 100.0 + offset + index
        rows.append(
            {
                "ts_code": symbol,
                "trade_date": trade_date.strftime("%Y%m%d"),
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "pre_close": close - 1.0,
                "change": 1.0,
                "pct_chg": 0.5,
                "vol": 1000.0,
                "amount": 10000.0,
            }
        )
    store.upsert_index(pd.DataFrame(rows, columns=MARKET_COLUMNS))


def test_market_style_overview_api_reads_standard_benchmark_cache(tmp_path: Path) -> None:
    """前端只能通过 API 读取标准基准缓存中的风格指数。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    store = BenchmarkIncrementalStore(paths.benchmark_increment_path)
    _seed_index(store, "932000.CSI", 0.0)
    _seed_index(store, "000300.SH", 20.0)
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.get("/api/market/style-overview?limit=60")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"] == "READY"
    assert payload["adjust_policy"] == "index_raw"
    assert [item["symbol"] for item in payload["styles"]] == ["932000.CSI", "000300.SH"]
    assert len(payload["styles"][0]["bars"]) == 60
