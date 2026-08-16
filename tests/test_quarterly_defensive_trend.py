"""季度防御趋势研究的组合与指纹测试。"""

from __future__ import annotations

import pandas as pd

import examples.quarterly_defensive_trend_study as study
from examples.quarterly_defensive_trend_study import (
    MarketTrendVolatilityController,
    build_market_trend_exposure,
    select_quarter_end_dates,
)
from runtime.paths import RuntimePaths


def test_select_quarter_end_dates_keeps_last_month() -> None:
    """证券选择每季度只发生一次。"""
    dates = [
        "20260130",
        "20260227",
        "20260331",
        "20260430",
        "20260529",
        "20260630",
    ]

    assert select_quarter_end_dates(dates) == ["20260331", "20260630"]


def test_market_trend_exposure_uses_long_moving_averages() -> None:
    """长期上升曲线应满仓，长期下降曲线应降至30%。"""
    dates = pd.bdate_range("2024-01-01", periods=300)
    rising = pd.Series(range(1, 301), index=dates, dtype=float)
    falling = pd.Series(range(300, 0, -1), index=dates, dtype=float)

    assert build_market_trend_exposure(rising).iloc[-1] == 1.0
    assert build_market_trend_exposure(falling).iloc[-1] == 0.30


def test_combined_controller_takes_stricter_limit() -> None:
    """市场趋势和组合波动率任一恶化，都只能使用30%仓位。"""
    dates = pd.bdate_range("2026-01-01", periods=3)
    controller = MarketTrendVolatilityController(
        pd.Series([1.0, 0.30, 1.0], index=dates)
    )

    assert controller.update(
        dates[0],
        volatility=0.20,
        drawdown=0.0,
        daily_return=0.0,
    ) == 1.0
    assert controller.update(
        dates[1],
        volatility=0.20,
        drawdown=0.0,
        daily_return=0.0,
    ) == 0.30
    assert controller.update(
        dates[2],
        volatility=0.50,
        drawdown=0.0,
        daily_return=0.0,
    ) == 0.30


def test_reused_quarterly_study_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    """相同指纹必须在行情物化和回测前复用。"""
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-quarterly-run"}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("must not calculate")),
    )

    result = study.run_study(RuntimePaths(tmp_path), "20260723")

    assert result["reused"] is True
    assert result["run_fingerprint"] == "same-quarterly-run"
