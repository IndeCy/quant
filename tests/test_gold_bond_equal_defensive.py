"""黄金国债等权防守策略固定门槛测试。"""

from __future__ import annotations

from examples import gold_bond_equal_defensive_study as study


def test_research_definition_is_fixed_equal_weight_without_overlay() -> None:
    """独立策略只能是固定50/50，不得暗中选择权重或加风险层。"""
    assert study.RESEARCH_SPEC.definition["asset_allocation"] == {
        "518880.SH": 0.5,
        "511010.SH": 0.5,
    }
    assert study.RESEARCH_SPEC.definition["risk_overlay"] == "none"


def test_gate_rejects_quality_correlation_above_limit() -> None:
    """防守策略必须保持与Quality的低相关性。"""
    metrics = {
        key: {
            "annualized_return": 0.08,
            "max_drawdown": -0.15,
            "sharpe": 0.90,
            "calmar": 0.53,
            "excess_return": 0.10,
            "annual_turnover": 0.3,
        }
        for key in [*study.FOLDS, "full"]
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2015, 2027)
    }

    gate = study.evaluate_gate(metrics, annual, 0.31)

    assert gate["passed"] is False
    assert gate["checks"]["quality_correlation_at_most_030"] is False
