"""Market Beta Observatory API helpers。"""

from __future__ import annotations

from runtime.paths import RuntimePaths
from monitoring.repository import MonitoringRepository


def latest_market_beta(paths: RuntimePaths) -> dict[str, object]:
    """读取最新 beta 快照，缺失时返回中性占位。"""
    latest = MonitoringRepository(paths.monitoring_path).load_latest_market_beta()
    if latest is not None:
        return latest
    return {
        "trade_date": "",
        "beta_state": "NEUTRAL",
        "beta_score": 50.0,
        "trend_score": 15.0,
        "breadth_score": 12.5,
        "sentiment_score": 10.0,
        "liquidity_score": 7.5,
        "funding_score": 2.5,
        "valuation_score": 2.5,
        "risk_level": "MEDIUM",
        "reasons": ["尚未生成 beta 观测快照"],
    }


def market_beta_series(paths: RuntimePaths, limit: int = 120) -> list[dict[str, object]]:
    """读取 beta 快照历史。"""
    return MonitoringRepository(paths.monitoring_path).load_market_beta_history(limit=limit)
