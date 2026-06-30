"""主线链动历史回测资产化测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.cache import MarketDataCache
from backtest.chain_selection import ChainDefinition, ChainStock
from backtest.paper_trading import PaperTradingStore
from monitoring.mainline_backtest import sync_mainline_chain_backtest_history
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths


def _bars(start: str, periods: int, first: float, step: float) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=periods)
    closes = [first + index * step for index in range(periods)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [1_000_000.0] * periods,
            "amount": [10_000_000.0] * periods,
        },
        index=dates,
    )


def test_sync_mainline_chain_backtest_history_writes_monitoring_curve(tmp_path: Path, monkeypatch) -> None:
    """主线链动回测历史应写入统一监控表，供前端展示长曲线。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    chains = [ChainDefinition("测试链", "CHAIN_PROXY", [ChainStock("A1", "测试股票", "测试链", "环节")])]
    monkeypatch.setattr("monitoring.mainline_backtest.build_default_chain_definitions", lambda: chains)
    cache = MarketDataCache(paths.data_dir / "market_cache.sqlite3")
    try:
        cache.upsert_bars("tencent", "CHAIN_PROXY", "1d", "qfq", _bars("2025-01-01", 170, 100.0, 0.20))
        cache.upsert_bars("tencent", "A1", "1d", "qfq", _bars("2025-01-01", 170, 20.0, 0.12))
        cache.upsert_bars("tencent", "000001.SH", "1d", "none", _bars("2025-01-01", 170, 3000.0, 1.0))
    finally:
        cache.close()

    summary = sync_mainline_chain_backtest_history(paths)
    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("mainline_chain_b")

    assert summary["status"] == "SUCCESS"
    assert summary["rows"] == len(history)
    assert len(history) >= 120
    assert history.iloc[-1]["strategy_name"] == "主线链动策略"


def test_backtest_history_stops_before_first_shadow_snapshot(tmp_path: Path, monkeypatch) -> None:
    """存在真实观察快照时，回测历史只写到快照前，避免同日混用两种口径。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    chains = [ChainDefinition("测试链", "CHAIN_PROXY", [ChainStock("A1", "测试股票", "测试链", "环节")])]
    monkeypatch.setattr("monitoring.mainline_backtest.build_default_chain_definitions", lambda: chains)
    cache = MarketDataCache(paths.data_dir / "market_cache.sqlite3")
    try:
        cache.upsert_bars("tencent", "CHAIN_PROXY", "1d", "qfq", _bars("2025-01-01", 180, 100.0, 0.20))
        cache.upsert_bars("tencent", "A1", "1d", "qfq", _bars("2025-01-01", 180, 20.0, 0.12))
        cache.upsert_bars("tencent", "000001.SH", "1d", "none", _bars("2025-01-01", 180, 3000.0, 1.0))
    finally:
        cache.close()
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        account_id = store.create_account("主线链动策略", "Mainline_Chain_Momentum", 1_000_000, "000001.SH", "上证指数", "2025-01-01")
        store.record_daily_snapshot(
            account_id,
            "2025-09-15",
            total_value=1_000_000,
            cash=100_000,
            position_value=900_000,
            strategy_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            strongest_chain="测试链",
            rebalance_signal="NONE",
            target_symbols=["A1"],
        )
    finally:
        store.close()

    sync_mainline_chain_backtest_history(paths)
    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("mainline_chain_b")

    assert history["trade_date"].max() < "20250915"
