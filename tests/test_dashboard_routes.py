"""总览首屏聚合 API 测试。"""

from api.dashboard_routes import _compact_strategy_series


def test_compact_strategy_series_keeps_dashboard_fields_only() -> None:
    rows = [
        {
            "trade_date": "20260727",
            "strategy_id": "quality_overlay",
            "nav": 1.2,
            "paper_nav": 1.1,
            "risk_adjusted_nav": 1.15,
            "benchmark_nav": 1.05,
            "drawdown": -0.02,
            "cumulative_return": 0.2,
            "volatility_20": 0.18,
        }
    ]

    compact = _compact_strategy_series(rows)

    assert compact == [
        {
            "trade_date": "20260727",
            "strategy_id": "quality_overlay",
            "nav": 1.2,
            "paper_nav": 1.1,
            "risk_adjusted_nav": 1.15,
            "benchmark_nav": 1.05,
            "drawdown": -0.02,
            "cumulative_return": 0.2,
        }
    ]
