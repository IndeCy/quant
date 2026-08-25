"""Quality Value LowVol 分级风险恢复规则测试。"""

from __future__ import annotations

import pandas as pd

from examples.quality_value_lowvol_risk_recovery_study import (
    StatefulRecoveryController,
    evaluate_gate,
)


def test_high_volatility_immediately_reduces_exposure() -> None:
    controller = StatefulRecoveryController()

    exposure = controller.update(
        pd.Timestamp("2026-01-05"),
        volatility=0.46,
        drawdown=-0.08,
        daily_return=-0.02,
    )

    assert exposure == 0.30
    assert controller.transitions[-1]["reason"] == "volatility_trigger"


def test_recovery_requires_stability_drawdown_repair_and_steps() -> None:
    controller = StatefulRecoveryController(exposure=0.30, low_drawdown=-0.15)

    for day, drawdown in enumerate([-0.145, -0.14, -0.13], start=1):
        exposure = controller.update(
            pd.Timestamp(f"2026-01-0{day}"),
            volatility=0.40,
            drawdown=drawdown,
            daily_return=0.01,
        )

    assert exposure == 0.50
    assert controller.stable_days == 0
    assert controller.transitions[-1]["to_exposure"] == 0.50


def test_critical_drawdown_blocks_recovery() -> None:
    controller = StatefulRecoveryController(exposure=0.30, stable_days=2, low_drawdown=-0.25)

    exposure = controller.update(
        pd.Timestamp("2026-01-05"),
        volatility=0.40,
        drawdown=-0.21,
        daily_return=0.01,
    )

    assert exposure == 0.30


def test_gate_is_fixed_before_research_result() -> None:
    baseline = {"execution_cost": 100.0}
    recovery = {
        "annualized_return": 0.11,
        "max_drawdown": -0.24,
        "calmar": 0.46,
        "execution_cost": 105.0,
    }

    assert evaluate_gate(baseline, recovery)["passed"] is True
    recovery["max_drawdown"] = -0.26
    assert evaluate_gate(baseline, recovery)["passed"] is False
