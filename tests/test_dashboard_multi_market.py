"""Dashboard多基准大盘模块测试。"""

from __future__ import annotations

import pandas as pd

from monitoring.dashboard_data import build_dashboard_payload
from monitoring.repository import MonitoringRepository


def test_dashboard_payload_can_export_multiple_market_benchmarks(tmp_path) -> None:
    """大盘模块需要同时支持510300与上证指数。"""
    repo = MonitoringRepository(tmp_path / "monitoring.sqlite3")
    repo.upsert_strategy_daily(
        pd.DataFrame(
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
    )
    for benchmark_id in ["510300", "000001.SH"]:
        repo.upsert_market_daily(
            pd.DataFrame(
                [
                    {
                        "trade_date": "20240102",
                        "benchmark_id": benchmark_id,
                        "benchmark_nav": 1.0,
                        "benchmark_return": 0.0,
                        "benchmark_drawdown": 0.0,
                        "ma60": 1.0,
                        "ma120": 1.0,
                        "trend_state": "UP",
                        "breadth_up_count": 0,
                        "breadth_down_count": 0,
                        "limit_up_count": 0,
                        "limit_down_count": 0,
                    }
                ]
            )
        )

    payload = build_dashboard_payload(repo, strategy_id="quality_overlay", benchmark_ids=["510300", "000001.SH"])

    assert set(payload["market_series_by_id"]) == {"510300", "000001.SH"}
    assert payload["market_summaries"]["000001.SH"]["trend_state"] == "UP"
