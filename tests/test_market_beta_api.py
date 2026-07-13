"""Market Beta Observatory API 测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths


def test_market_beta_api_returns_latest_and_series(tmp_path) -> None:
    """前端应能通过 API 读取最新 beta 状态和历史序列。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    MonitoringRepository(paths.monitoring_path).upsert_market_beta(
        {
            "trade_date": "20260624",
            "beta_state": "BETA_ON",
            "beta_score": 72.0,
            "trend_score": 24.0,
            "breadth_score": 20.0,
            "sentiment_score": 15.0,
            "liquidity_score": 8.0,
            "funding_score": 2.5,
            "valuation_score": 2.5,
            "risk_level": "LOW",
            "reasons": ["趋势顺风"],
        }
    )
    client = TestClient(create_app(LocalApiService(paths)))

    latest = client.get("/api/market/beta/latest").json()
    series = client.get("/api/market/beta/series").json()

    assert latest["beta_state"] == "BETA_ON"
    assert latest["reasons"] == ["趋势顺风"]
    assert series[0]["trade_date"] == "20260624"
