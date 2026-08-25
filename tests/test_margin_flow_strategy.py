"""融资净买入强度策略组合与门槛测试。"""

from __future__ import annotations

import pandas as pd

from examples import margin_flow_strategy_study as study


def test_margin_strategy_keeps_empty_month_as_cash() -> None:
    """空候选月必须明确目标为空，不能继续持有上月股票。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20220131", "20220131"],
            "symbol": ["A", "B"],
            "margin_flow_intensity": [0.02, 0.01],
        }
    )

    targets, _, counts = study.build_margin_flow_targets(
        ["20220131", "20220228"],
        candidates,
    )

    assert targets["20220228"] == {}
    assert counts["empty_months"] == 1


def test_margin_strategy_gate_rejects_excessive_turnover() -> None:
    """收益看似达标但换手超过冻结上限时仍必须拒绝。"""
    metric = {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.20,
        "annual_turnover": 11.0,
    }
    metrics = {name: dict(metric) for name in [*study.FOLDS, "full"]}

    gate = study.evaluate_gate(metrics, 0.50)

    assert gate["passed"] is False
    assert gate["checks"]["annual_turnover_below_10x"] is False


def test_margin_strategy_declares_feasibility_dependency() -> None:
    assert study.RESEARCH_SPEC.definition["dependency"] == study.FEASIBILITY_ID
