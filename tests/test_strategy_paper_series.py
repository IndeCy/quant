"""策略曲线合并 Paper 净值测试。"""

from __future__ import annotations

import pandas as pd

from api.service import LocalApiService
from backtest.paper_trading import PaperTradingStore
from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths


def test_strategy_series_includes_paper_nav(tmp_path) -> None:
    """策略大盘应同时展示理论净值和 Paper 撮合后的实际净值。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    dates = pd.to_datetime(["2026-06-23", "2026-06-24"])
    monitoring = MonitoringRepository(paths.monitoring_path)
    monitoring.upsert_strategy_daily(
        build_strategy_monitor_frame(
            strategy_id="quality_overlay",
            strategy_name="Quality Alpha V1",
            daily_values=pd.Series([100.0, 103.0], index=dates),
            benchmark_values=pd.Series([1.0, 1.02], index=dates),
            exposure=pd.Series([1.0, 0.3], index=dates),
            total_cost=0.0,
            failed_order_count=0,
            turnover_notional=0.0,
        )
    )
    store = PaperTradingStore(paths.paper_trading_path)
    account_id = store.create_account("Quality Alpha V1", "quality_overlay", 1000000, "510300", "沪深300ETF", "20260623")
    store.record_daily_snapshot(account_id, "2026-06-23", 1000000, 1000000, 0, 0.0, 0.0, 0.0, "", "", [])
    store.record_daily_snapshot(account_id, "2026-06-24", 990000, 100000, 890000, -0.01, 0.02, -0.03, "", "", [])
    store.close()
    service = LocalApiService(paths)

    series = service.strategy_series("quality_overlay")

    assert series[0]["paper_nav"] == 1.0
    assert series[1]["paper_nav"] == 0.99
