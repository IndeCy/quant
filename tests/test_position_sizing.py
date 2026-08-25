"""
测试仓位管理模块
"""

import pandas as pd

from backtest.position_sizing import (
    KellyEstimate,
    KellyPositionSizer,
    calculate_kelly_fraction,
    estimate_kelly_from_returns,
)


def test_calculate_kelly_fraction_from_win_rate_and_payoff():
    """标准凯利公式应按胜率和赔率计算最优资金比例。"""
    fraction = calculate_kelly_fraction(win_rate=0.6, win_loss_ratio=2.0)

    assert round(fraction, 2) == 0.4


def test_calculate_kelly_fraction_clamps_negative_edge_to_zero():
    """没有正期望优势时，基础仓位应降为 0。"""
    fraction = calculate_kelly_fraction(win_rate=0.4, win_loss_ratio=1.0)

    assert fraction == 0.0


def test_estimate_kelly_from_return_series():
    """应能从历史收益序列估计胜率、赔率和凯利值。"""
    returns = pd.Series([0.02, -0.01, 0.03, -0.01, 0.01])

    estimate = estimate_kelly_from_returns(returns)

    assert estimate.sample_size == 5
    assert round(estimate.win_rate, 2) == 0.6
    assert round(estimate.win_loss_ratio, 2) == 2.0
    assert round(estimate.raw_fraction, 2) == 0.4


def test_position_sizer_uses_fractional_kelly_and_cap():
    """仓位建议应支持半凯利和最大仓位上限，避免过度下注。"""
    sizer = KellyPositionSizer(fractional_kelly=0.5, max_total_exposure=0.3)
    estimate = KellyEstimate(
        win_rate=0.6,
        win_loss_ratio=2.0,
        raw_fraction=0.4,
        sample_size=20,
    )

    suggestion = sizer.suggest_total_exposure(estimate)

    assert suggestion.total_exposure == 0.2
    assert suggestion.reason == "KELLY"


def test_position_sizer_returns_zero_when_sample_too_small():
    """样本不足时不应给出主动仓位建议。"""
    sizer = KellyPositionSizer(min_sample_size=10)
    estimate = KellyEstimate(
        win_rate=0.8,
        win_loss_ratio=3.0,
        raw_fraction=0.73,
        sample_size=5,
    )

    suggestion = sizer.suggest_total_exposure(estimate)

    assert suggestion.total_exposure == 0.0
    assert suggestion.reason == "INSUFFICIENT_SAMPLE"


def test_allocate_equal_weights_across_targets():
    """总仓位应能等权分配到目标持仓股票。"""
    sizer = KellyPositionSizer()

    weights = sizer.allocate_equal_weights(["A", "B", "C"], total_exposure=0.6)

    assert {symbol: round(weight, 2) for symbol, weight in weights.items()} == {
        "A": 0.2,
        "B": 0.2,
        "C": 0.2,
    }


def test_mainline_chain_targets_can_use_kelly_sized_weights():
    """主线链动策略目标股票应能套用凯利总仓位做等权分配。"""
    returns = pd.Series([0.04, -0.02, 0.03, 0.01, -0.01] * 6)
    estimate = estimate_kelly_from_returns(returns)
    sizer = KellyPositionSizer(fractional_kelly=0.5, max_total_exposure=0.8)

    suggestion = sizer.suggest_total_exposure(estimate)
    weights = sizer.allocate_equal_weights(
        ["000063.SZ", "300308.SZ", "300502.SZ", "601138.SH"],
        suggestion.total_exposure,
    )

    assert 0 < suggestion.total_exposure <= 0.8
    assert set(weights) == {"000063.SZ", "300308.SZ", "300502.SZ", "601138.SH"}
    assert round(sum(weights.values()), 6) == round(suggestion.total_exposure, 6)
