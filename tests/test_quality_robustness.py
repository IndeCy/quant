"""Quality 风险层稳健性分析测试。"""

import pandas as pd
import pytest

from backtest.quality_robustness import (
    build_trigger_episodes,
    calculate_avoided_loss,
    rank_parameters,
    slice_performance,
)


def test_rank_parameters_uses_locked_priority_order() -> None:
    """依次按夏普、Calmar、回撤绝对值、平均仓位排序。"""
    frame = pd.DataFrame(
        [
            {"参数": "A", "夏普比率": 0.8, "Calmar": 0.4, "最大回撤": -0.2, "平均仓位": 0.9},
            {"参数": "B", "夏普比率": 0.8, "Calmar": 0.5, "最大回撤": -0.3, "平均仓位": 0.7},
            {"参数": "C", "夏普比率": 0.8, "Calmar": 0.5, "最大回撤": -0.2, "平均仓位": 0.7},
            {"参数": "D", "夏普比率": 0.8, "Calmar": 0.5, "最大回撤": -0.2, "平均仓位": 0.8},
        ]
    )

    ranked = rank_parameters(frame)

    assert ranked["参数"].tolist() == ["D", "C", "B", "A"]


def test_slice_performance_rebases_strategy_and_benchmark() -> None:
    dates = pd.bdate_range("2024-01-01", periods=5)
    values = pd.Series([100.0, 110.0, 99.0, 108.0, 121.0], index=dates)
    benchmark = pd.Series([100.0, 102.0, 101.0, 104.0, 110.0], index=dates)

    metrics = slice_performance(values, benchmark, dates[1], dates[4])

    assert metrics["区间收益"] == pytest.approx(0.10)
    assert metrics["最大回撤"] == pytest.approx(-0.10)
    assert metrics["基准收益"] == pytest.approx(110 / 102 - 1)
    assert metrics["超额收益"] == pytest.approx(0.10 - (110 / 102 - 1))


def test_build_trigger_episodes_merges_consecutive_trading_days() -> None:
    dates = pd.bdate_range("2024-01-01", periods=5)
    exposure = pd.Series([1.0, 0.3, 0.3, 1.0, 0.3], index=dates)
    volatility = pd.Series([0.2, 0.46, 0.48, 0.4, 0.5], index=dates)

    episodes = build_trigger_episodes(exposure, volatility, threshold=0.45, window=20)

    assert episodes["触发日期"].tolist() == [dates[1], dates[4]]
    assert episodes["持续交易日"].tolist() == [2, 1]
    assert episodes.iloc[0]["触发原因"] == "20日组合年化波动率46.00%超过阈值45.00%"


def test_calculate_avoided_loss_compares_same_episode_window() -> None:
    dates = pd.bdate_range("2024-01-01", periods=4)
    overlay = pd.Series([100.0, 100.0, 95.0, 94.0], index=dates)
    baseline = pd.Series([100.0, 100.0, 90.0, 80.0], index=dates)
    episodes = pd.DataFrame({"触发日期": [dates[1]], "结束日期": [dates[2]]})

    attributed = calculate_avoided_loss(episodes, overlay, baseline)

    # T 日收盘触发，T+1 执行，因此归因终点需包含最后信号日的下一交易日。
    assert attributed.iloc[0]["风险层区间收益"] == pytest.approx(-0.06)
    assert attributed.iloc[0]["原策略区间收益"] == pytest.approx(-0.20)
    assert attributed.iloc[0]["避免损失"] == pytest.approx(0.14)
