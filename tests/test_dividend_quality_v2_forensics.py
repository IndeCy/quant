"""Dividend Quality V2 归因辅助函数测试。"""

import pandas as pd

from examples.dividend_quality_v2_forensics import consecutive_dividend_years, drawdown_window


def test_consecutive_dividend_years_stops_at_first_gap() -> None:
    """连续分红年限遇到缺口年份应停止计数。"""
    annual_cash = pd.Series({2026: 1.0, 2025: 0.8, 2023: 0.7})

    assert consecutive_dividend_years(annual_cash, 2026) == 2


def test_drawdown_window_finds_peak_and_trough() -> None:
    """最大回撤应定位到回撤前高点和谷底。"""
    values = pd.Series(
        [100.0, 120.0, 90.0, 80.0, 110.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
    )

    peak, trough, drawdown = drawdown_window(values)

    assert peak == pd.Timestamp("2024-01-02")
    assert trough == pd.Timestamp("2024-01-04")
    assert round(drawdown, 4) == -0.3333
