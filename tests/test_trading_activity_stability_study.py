"""交易活跃度稳定性正式研究语义测试。"""

from __future__ import annotations

import pandas as pd

from examples import trading_activity_stability_study as study


def test_research_spec_uses_explicit_grid_risk_mode() -> None:
    """风险层必须显式执行20日、45%、30%的 GRID 语义。"""
    assert study.RESEARCH_SPEC.definition["risk_overlay"] == {
        "mode": "GRID",
        "window": 20,
        "threshold": 0.45,
        "reduced_exposure": 0.30,
    }


def test_targets_select_lowest_activity_volatility() -> None:
    """Top40 必须选择成交额路径最稳定的股票。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 45,
            "symbol": [f"S{i:03d}" for i in range(45)],
            "name": [f"股票{i}" for i in range(45)],
            "activity_volatility": [float(i) for i in range(45)],
            "activity_observations": [60] * 45,
            "ret120": [0.0] * 45,
            "vol60": [0.02] * 45,
            "adv_rmb": [50_000_000.0] * 45,
        }
    )

    _, holdings, counts = study.build_targets(frame)

    assert len(holdings) == 40
    assert set(holdings["symbol"]) == {f"S{i:03d}" for i in range(40)}
    assert counts["latest"] == 45.0


def test_gate_rejects_excessive_turnover() -> None:
    """收益达标但年化换手超过10倍时仍不得晋级。"""
    good = {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.05,
        "annual_turnover": 5.0,
        "execution_cost_impact": 0.01,
    }
    metrics = {key: dict(good) for key in [*study.FOLDS, "full"]}
    metrics["full"]["annual_turnover"] = 10.1

    gate = study.evaluate_gate(metrics, quality_correlation=0.4)

    assert gate["passed"] is False
    assert gate["checks"]["annual_turnover_below_10x"] is False
