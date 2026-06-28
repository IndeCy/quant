import pandas as pd
import pytest

from examples.quality_risk_layer_research import (
    combined_exposure,
    drawdown_exposure,
    index_crash_exposure,
    single_threshold_exposure,
    volatility_target_exposure,
)


def test_volatility_target_exposure_thresholds():
    assert volatility_target_exposure(0.39) == 1.0
    assert volatility_target_exposure(0.45) == 0.5
    assert volatility_target_exposure(0.55) == 0.3


def test_index_crash_exposure_thresholds():
    assert index_crash_exposure(-0.10) == 1.0
    assert index_crash_exposure(-0.16) == 0.5
    assert index_crash_exposure(-0.21) == 0.2


def test_drawdown_exposure_thresholds():
    assert drawdown_exposure(-0.05) == 1.0
    assert drawdown_exposure(-0.15) == 0.7
    assert drawdown_exposure(-0.25) == 0.4
    assert drawdown_exposure(-0.35) == 0.2


def test_combined_exposure_uses_stricter_control():
    assert combined_exposure(volatility=0.45, drawdown=-0.25) == pytest.approx(0.4)


def test_single_threshold_exposure_uses_grid_parameters():
    assert single_threshold_exposure(0.39, threshold=0.40, reduced_exposure=0.7) == 1.0
    assert single_threshold_exposure(0.41, threshold=0.40, reduced_exposure=0.7) == 0.7
