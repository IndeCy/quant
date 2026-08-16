"""监控指标计算测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from monitoring.metrics import build_market_monitor_frame, build_strategy_monitor_frame


def test_build_strategy_monitor_frame_outputs_nav_return_and_risk_columns() -> None:
    """策略净值应转换成可展示的收益、回撤和滚动风险指标。"""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    values = pd.Series([100.0, 110.0, 99.0], index=dates)
    benchmark = pd.Series([10.0, 10.5, 9.45], index=dates)
    exposure = pd.Series([1.0, 0.3], index=dates[1:])

    frame = build_strategy_monitor_frame(
        strategy_id="quality_overlay",
        strategy_name="Quality Overlay",
        daily_values=values,
        benchmark_values=benchmark,
        exposure=exposure,
        total_cost=12.5,
        failed_order_count=2,
        turnover_notional=55.0,
        volatility_windows=(2,),
    )

    assert list(frame["trade_date"]) == ["20240102", "20240103", "20240104"]
    assert frame.loc[0, "strategy_id"] == "quality_overlay"
    assert frame.loc[0, "nav"] == 1.0
    assert frame.loc[1, "daily_return"] == pytest.approx(0.10)
    assert frame.loc[2, "cumulative_return"] == pytest.approx(-0.01)
    assert frame.loc[2, "drawdown"] == pytest.approx(-0.10)
    assert frame.loc[2, "benchmark_nav"] == pytest.approx(0.945)
    assert frame.loc[2, "excess_return"] == pytest.approx(0.045)
    assert frame.loc[0, "exposure"] == 1.0
    assert frame.loc[1, "exposure"] == 1.0
    assert frame.loc[2, "exposure"] == 0.3
    assert frame.loc[2, "total_execution_cost"] == 12.5
    assert frame.loc[2, "failed_order_count"] == 2
    assert frame.loc[2, "turnover_notional"] == 55.0
    assert "volatility_2" in frame.columns


def test_build_market_monitor_frame_omits_unobserved_breadth_columns() -> None:
    """仅刷新基准曲线时不得用假 0 覆盖已存在的宽度和涨跌停观测。"""
    dates = pd.to_datetime(["2026-07-27", "2026-07-28"])
    values = pd.Series([100.0, 101.0], index=dates)

    frame = build_market_monitor_frame("510300", values)

    assert "breadth_up_count" not in frame.columns
    assert "breadth_down_count" not in frame.columns
    assert "limit_up_count" not in frame.columns
    assert "limit_down_count" not in frame.columns
