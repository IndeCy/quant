"""风格轮动诊断纯函数测试。"""

import pandas as pd
import pytest

from backtest.style_rotation_diagnostic import (
    build_lagged_rotation_curve,
    calculate_pb,
    find_longest_underwater,
    relative_strength_signals,
)


def test_find_longest_underwater_returns_longest_episode() -> None:
    dates = pd.bdate_range("2024-01-01", periods=8)
    values = pd.Series([100, 90, 95, 101, 99, 98, 97, 102], index=dates)

    episode = find_longest_underwater(values)

    assert episode["高点日期"] == dates[3]
    assert episode["开始日期"] == dates[4]
    assert episode["结束日期"] == dates[6]
    assert episode["恢复日期"] == dates[7]
    assert episode["持续交易日"] == 3


def test_calculate_pb_uses_unadjusted_price_and_positive_bps() -> None:
    assert calculate_pb(raw_close=12.0, bps=4.0) == 3.0
    assert calculate_pb(raw_close=12.0, bps=-1.0) is None


def test_relative_strength_signal_only_uses_history_through_signal_date() -> None:
    dates = pd.bdate_range("2024-01-01", periods=5)
    curves = {
        "Quality": pd.Series([100, 101, 102, 103, 104], index=dates),
        "Value": pd.Series([100, 102, 105, 104, 103], index=dates),
    }

    signals = relative_strength_signals(curves, [dates[2]], lookback=2)

    assert signals.loc[dates[2], "选择风格"] == "Value"
    assert signals.loc[dates[2], "信号可用日期"] == dates[3]


def test_rotation_curve_applies_signal_from_next_trading_day() -> None:
    dates = pd.bdate_range("2024-01-01", periods=4)
    curves = {
        "Quality": pd.Series([100, 100, 110, 121], index=dates),
        "Value": pd.Series([100, 100, 90, 81], index=dates),
    }
    signals = pd.DataFrame(
        {"选择风格": ["Value"], "信号可用日期": [dates[2]]}, index=[dates[1]]
    )

    rotation = build_lagged_rotation_curve(curves, signals, initial_value=100.0)

    assert rotation.loc[dates[1]] == pytest.approx(100.0)
    assert rotation.loc[dates[2]] == pytest.approx(90.0)
    assert rotation.loc[dates[3]] == pytest.approx(81.0)
