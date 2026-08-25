"""12-1月中期动量正式研究语义测试。"""

import pandas as pd

from examples import intermediate_momentum_study as study


def test_risk_overlay_uses_explicit_grid_semantics() -> None:
    """正式回测必须执行冻结的GRID风险层。"""
    assert study.RESEARCH_SPEC.definition["risk_overlay"] == {
        "mode": "GRID",
        "window": 20,
        "threshold": 0.45,
        "reduced_exposure": 0.30,
    }


def test_targets_select_highest_intermediate_momentum() -> None:
    """Top40必须来自12-1月收益最高的股票。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 45,
            "symbol": [f"S{i:03d}" for i in range(45)],
            "name": [f"股票{i}" for i in range(45)],
            "intermediate_momentum": [float(i) for i in range(45)],
            "ret120": [0.0] * 45,
            "vol60": [0.02] * 45,
            "adv_rmb": [50_000_000.0] * 45,
        }
    )

    _, holdings, _ = study.build_targets(frame)

    assert set(holdings["symbol"]) == {f"S{i:03d}" for i in range(5, 45)}


def test_gate_rejects_too_few_positive_folds() -> None:
    """全期指标合格但正收益分段不足三个时仍不得晋级。"""
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
    metrics["2015_2017"]["annualized_return"] = -0.01
    metrics["2018_2020"]["annualized_return"] = -0.01

    gate = study.evaluate_gate(metrics, quality_correlation=0.4)

    assert gate["checks"]["at_least_three_positive_folds"] is False
    assert gate["passed"] is False
