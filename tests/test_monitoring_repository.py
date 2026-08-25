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
                "market_amount": 12000.0,
                "amount_ratio_20": 1.2,
                "ma20_above_ratio": 0.6,
                "zero_volume_ratio": 0.01,
            }
        ]
    )

    repo.upsert_market_daily(rows)
    rows.loc[0, "trend_state"] = "RISK"
    repo.upsert_market_daily(rows)

    history = repo.load_market_history("510300")

    assert len(history) == 1
    assert history.loc[0, "trend_state"] == "RISK"
    assert history.loc[0, "market_amount"] == 12000.0
    assert history.loc[0, "ma20_above_ratio"] == 0.6


def test_repository_preserves_market_observations_when_base_curve_is_refreshed(tmp_path) -> None:
    """基础基准曲线重写时不得清零已沉淀的宽度和成交额指标。"""
    repo = MonitoringRepository(tmp_path / "monitoring.sqlite3")
    enriched = pd.DataFrame(
        [
            {
                "trade_date": "20260727",
                "benchmark_id": "510300",
                "benchmark_nav": 1.0,
                "benchmark_return": 0.01,
                "benchmark_drawdown": -0.02,
                "ma60": 0.98,
                "ma120": 0.95,
                "trend_state": "UP",
                "breadth_up_count": 4000,
                "breadth_down_count": 1200,
                "market_amount": 2_000_000_000.0,
                "amount_ratio_20": 1.05,
                "ma20_above_ratio": 0.62,
            }
        ]
    )
    repo.upsert_market_daily(enriched)

    base_curve = enriched[
        [
            "trade_date",
            "benchmark_id",
            "benchmark_nav",
            "benchmark_return",
            "benchmark_drawdown",
            "ma60",
            "ma120",
            "trend_state",
        ]
    ].copy()
    base_curve.loc[0, "benchmark_nav"] = 1.01
    repo.upsert_market_daily(base_curve)

    latest = repo.load_market_history("510300").iloc[-1]
    assert latest["benchmark_nav"] == 1.01
    assert latest["breadth_up_count"] == 4000
    assert latest["breadth_down_count"] == 1200
    assert latest["market_amount"] == 2_000_000_000.0
    assert latest["amount_ratio_20"] == 1.05
    assert latest["ma20_above_ratio"] == 0.62


def test_repository_upserts_market_beta_snapshots(tmp_path) -> None:
    """Beta 观测快照按交易日幂等覆盖，并保留可解释原因。"""
    repo = MonitoringRepository(tmp_path / "monitoring.sqlite3")
    row = {
        "trade_date": "20260710",
        "beta_state": "BETA_OFF",
        "beta_score": 38.0,
        "trend_score": 8.0,
        "breadth_score": 7.0,
        "sentiment_score": 6.0,
        "liquidity_score": 7.5,
        "funding_score": 4.0,
        "valuation_score": 5.5,
        "risk_level": "ELEVATED",
        "reasons": ["指数低于MA120", "宽度偏弱"],
    }

    repo.upsert_market_beta(row)
    row["beta_score"] = 40.0
    repo.upsert_market_beta(row)

    latest = repo.load_latest_market_beta()
    history = repo.load_market_beta_history()

    assert latest is not None
    assert latest["beta_score"] == 40.0
    assert latest["reasons"] == ["指数低于MA120", "宽度偏弱"]
    assert len(history) == 1
