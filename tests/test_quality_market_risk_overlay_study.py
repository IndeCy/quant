import pandas as pd
import pytest

from examples.quality_market_risk_overlay_study import (
    build_market_exposure,
    build_overlay_targets,
)


def test_build_market_exposure_uses_requested_weak_exposure():
    curve = pd.Series(
        [1.0, 2.0, 3.0, 2.0, 1.0],
        index=pd.date_range("2024-01-01", periods=5),
    )

    exposure = build_market_exposure(curve, short_window=2, long_window=3, weak_exposure=0.3)

    assert exposure.iloc[-1] == pytest.approx(0.3)
    assert set(exposure.dropna().unique()).issubset({0.3, 1.0})


def test_build_overlay_targets_only_rebalances_on_monthly_or_exposure_change():
    calendar = list(pd.date_range("2024-01-01", periods=5))
    base = {"20240102": {"AAA": 1.0}}
    exposure = pd.Series([1.0, 1.0, 1.0, 0.0, 0.0], index=calendar)

    targets = build_overlay_targets(base, exposure, calendar)

    assert list(targets) == ["20240102", "20240104"]
    assert targets["20240102"] == {"AAA": 1.0}
    assert targets["20240104"] == {"AAA": 0.0}
