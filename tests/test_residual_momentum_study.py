"""走步双因子残差动量正式研究语义测试。"""

from __future__ import annotations

import pandas as pd

from examples import residual_momentum_study as study


def test_research_definition_freezes_execution_and_risk() -> None:
    """正式研究必须冻结M0执行和既有风险层。"""
    definition = study.RESEARCH_SPEC.definition

    assert definition["execution"] == {
        "model": "M0",
        "lag": 1,
        "adjust": "qfq",
        "slippage_bps": 5.0,
    }
    assert definition["risk_overlay"] == {
        "mode": "GRID",
        "window": 20,
        "threshold": 0.45,
        "reduced_exposure": 0.30,
    }


def test_targets_select_highest_residual_momentum() -> None:
    """Top40必须来自累计特质收益最高的股票。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 45,
            "symbol": [f"S{i:03d}" for i in range(45)],
            "name": [f"股票{i}" for i in range(45)],
            "residual_momentum": [float(i) for i in range(45)],
            "market_beta": [1.0] * 45,
            "size_beta": [0.0] * 45,
            "ret120": [0.0] * 45,
            "vol60": [0.02] * 45,
            "adv_rmb": [50_000_000.0] * 45,
        }
    )

    _, holdings, _ = study.build_targets(frame)

    assert set(holdings["symbol"]) == {
        f"S{i:03d}" for i in range(5, 45)
    }


def test_gate_rejects_failed_midcap_residual() -> None:
    """原始业绩合格但中盘残差失败时不得晋级。"""
    good = {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.05,
        "annual_turnover": 5.0,
        "execution_cost_impact": 0.01,
    }
    metrics = {
        key: dict(good)
        for key in [*study.FOLDS, "full"]
    }

    gate = study.evaluate_gate(
        metrics,
        quality_correlation=0.4,
        style_residual={"gate_passed": False},
    )

    assert gate["checks"]["walk_forward_midcap_residual_gate"] is False
    assert gate["passed"] is False
