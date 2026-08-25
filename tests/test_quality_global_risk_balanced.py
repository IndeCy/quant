from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from examples import quality_global_risk_balanced_study as study


def _run(returns: list[float]) -> SimpleNamespace:
    values = pd.Series(returns, index=pd.bdate_range("2015-01-01", periods=len(returns)))
    nav = (1.0 + values).cumprod()
    return SimpleNamespace(result=SimpleNamespace(daily_values=nav))


def test_inverse_vol_calibration_uses_only_declared_early_period() -> None:
    quality = _run([0.02, -0.02] * 400)
    global_defensive = _run([0.01, -0.01] * 400)
    result = study.calibrate_quality_weight(quality, global_defensive)
    assert 0.30 < result["quality_weight"] < 0.35
    assert result["global_weight"] == 1.0 - result["quality_weight"]


def test_calibration_contract_freezes_oos_start_after_calibration() -> None:
    definition = study.RESEARCH_SPEC.definition
    assert definition["calibration"]["period"] == ["20150101", "20181231"]
    assert definition["calibration"]["frozen_after_calibration"] is True
    assert definition["evaluation"]["start"] == "20190101"
    assert definition["evaluation"]["weight_grid"] is False
