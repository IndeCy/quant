"""多策略市场指数对比 API 测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd

from api.local_server import create_app
from api.market_index import (
    COMPARISON_EXPERIMENT_ID,
    COMPARISON_SERIES_IDS,
)
from api.service import LocalApiService
from data.tushare_benchmark_incremental import BenchmarkIncrementalStore, MARKET_COLUMNS
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def _seed_index(store: BenchmarkIncrementalStore, symbol: str, closes: list[float]) -> None:
    rows = []
    for trade_date, close in zip(pd.bdate_range("2026-07-01", periods=len(closes)), closes, strict=True):
        rows.append(
            {
                "ts_code": symbol,
                "trade_date": trade_date.strftime("%Y%m%d"),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "pre_close": close,
                "change": 0.0,
                "pct_chg": 0.0,
                "vol": 1000.0,
                "amount": 10000.0,
            }
        )
    store.upsert_index(pd.DataFrame(rows, columns=MARKET_COLUMNS))


def test_market_index_comparison_api_returns_normalized_raw_indices(tmp_path: Path) -> None:
    """接口只返回上证和沪深300，并分别归一到所取窗口起点。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    store = BenchmarkIncrementalStore(paths.benchmark_increment_path)
    _seed_index(store, "000001.SH", [3000.0, 3030.0, 3060.0])
    _seed_index(store, "000300.SH", [4000.0, 3960.0, 4040.0])
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.get("/api/market/index-comparison?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"] == "READY"
    assert payload["adjust_policy"] == "index_raw"
    assert [item["symbol"] for item in payload["indices"]] == ["000001.SH", "000300.SH"]
    assert payload["indices"][0]["points"][0]["nav"] == 1.0
    assert payload["indices"][0]["points"][1]["nav"] == 3060.0 / 3030.0
    assert payload["indices"][1]["points"][1]["nav"] == 4040.0 / 3960.0


def test_market_index_comparison_api_adds_structured_research_curves(
    tmp_path: Path,
) -> None:
    """通过门槛的实验净值应与指数一起进入多策略图。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    store = BenchmarkIncrementalStore(paths.benchmark_increment_path)
    _seed_index(store, "000001.SH", [3000.0, 3030.0])
    _seed_index(store, "000300.SH", [4000.0, 4040.0])
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_experiment(
        {
            "experiment_id": COMPARISON_EXPERIMENT_ID,
            "name": "纳指黄金60/40",
            "category": "allocation",
            "status": "completed",
        }
    )
    run_id = f"{COMPARISON_EXPERIMENT_ID}:20260728:001"
    repository.record_experiment_run(
        experiment_id=COMPARISON_EXPERIMENT_ID,
        run_id=run_id,
        run_date="20260728",
        status="SUCCESS",
        output_dir=paths.runs_dir / "experiments" / "comparison",
        outcome="PASSED_RESEARCH_GATE",
        data_as_of="20260728",
    )
    rows = []
    for series_id, name in zip(
        COMPARISON_SERIES_IDS,
        ["纳指黄金60/40（V3）", "标普500ETF（513500）"],
        strict=True,
    ):
        rows.extend(
            [
                {
                    "series_id": series_id,
                    "series_name": name,
                    "trade_date": "20260701",
                    "nav": 1.0,
                    "adjust_policy": "qfq_m0_t1_5bps",
                },
                {
                    "series_id": series_id,
                    "series_name": name,
                    "trade_date": "20260702",
                    "nav": 1.01,
                    "adjust_policy": "qfq_m0_t1_5bps",
                },
            ]
        )
    repository.replace_experiment_series(
        run_id,
        COMPARISON_EXPERIMENT_ID,
        rows,
    )
    client = TestClient(create_app(LocalApiService(paths)))

    payload = client.get("/api/market/index-comparison").json()

    assert payload["adjust_policy"] == "mixed"
    assert [item["name"] for item in payload["indices"]] == [
        "上证指数",
        "沪深300",
        "纳指黄金60/40（V3）",
        "标普500ETF（513500）",
    ]
    assert [item["series_kind"] for item in payload["indices"]] == [
        "market_index",
        "market_index",
        "research",
        "research",
    ]
