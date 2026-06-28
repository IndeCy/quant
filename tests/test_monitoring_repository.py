"""监控 SQLite 仓库测试。"""

from __future__ import annotations

import pandas as pd

from monitoring.repository import MonitoringRepository


def test_repository_upserts_strategy_rows_and_reads_latest(tmp_path) -> None:
    """监控数据按策略和日期幂等覆盖，避免重复快照污染曲线。"""
    repo = MonitoringRepository(tmp_path / "monitoring.sqlite3")
    rows = pd.DataFrame(
        [
            {
                "trade_date": "20240102",
                "strategy_id": "quality_overlay",
                "strategy_name": "Quality Overlay",
                "nav": 1.0,
                "daily_return": 0.0,
                "cumulative_return": 0.0,
                "benchmark_id": "510300",
                "benchmark_nav": 1.0,
                "benchmark_return": 0.0,
                "excess_return": 0.0,
                "drawdown": 0.0,
                "max_drawdown": 0.0,
                "volatility_20": 0.0,
                "volatility_60": 0.0,
                "sharpe_rolling": 0.0,
                "exposure": 1.0,
                "turnover_notional": 0.0,
                "total_execution_cost": 0.0,
                "failed_order_count": 0,
            }
        ]
    )

    repo.upsert_strategy_daily(rows)
    rows.loc[0, "nav"] = 1.05
    repo.upsert_strategy_daily(rows)

    history = repo.load_strategy_history("quality_overlay")
    latest = repo.load_latest_strategy_metrics("quality_overlay")

    assert len(history) == 1
    assert latest is not None
    assert latest["nav"] == 1.05


def test_repository_upserts_market_rows(tmp_path) -> None:
    """大盘模块也按日期和基准幂等覆盖。"""
    repo = MonitoringRepository(tmp_path / "monitoring.sqlite3")
    rows = pd.DataFrame(
        [
            {
                "trade_date": "20240102",
                "benchmark_id": "510300",
                "benchmark_nav": 1.0,
                "benchmark_return": 0.0,
                "benchmark_drawdown": 0.0,
                "ma60": 1.0,
                "ma120": 0.9,
                "trend_state": "UP",
                "breadth_up_count": 10,
                "breadth_down_count": 5,
                "limit_up_count": 1,
                "limit_down_count": 0,
            }
        ]
    )

    repo.upsert_market_daily(rows)
    rows.loc[0, "trend_state"] = "RISK"
    repo.upsert_market_daily(rows)

    history = repo.load_market_history("510300")

    assert len(history) == 1
    assert history.loc[0, "trend_state"] == "RISK"
