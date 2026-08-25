"""Piotroski 价值因子和固定验收门槛测试。"""

from __future__ import annotations

import pandas as pd

from examples import piotroski_value_study as study
from factors.piotroski import score_piotroski_value_frame


def test_piotroski_factor_uses_value_pool_and_fscore_priority() -> None:
    """只保留价值池高分股，9 分必须排在 8 分之前。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "f_score": [8, 9, 9, 7, 8],
            "book_to_market": [5.0, 4.0, 3.0, 2.0, 1.0],
        }
    )

    result = score_piotroski_value_frame(
        frame,
        high_score_threshold=8,
        value_quantile=0.60,
    )

    assert result["symbol"].tolist() == ["B", "C", "A"]
    assert result["factor_score"].is_monotonic_decreasing


def test_piotroski_target_builder_keeps_empty_month_as_cash() -> None:
    """没有候选的调仓月必须生成空目标，而不是沿用旧持仓。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20220131", "20220131"],
            "symbol": ["A", "B"],
            "f_score": [9, 8],
            "book_to_market": [2.0, 1.0],
        }
    )

    targets, _, coverage = study.build_piotroski_targets(
        ["20220131", "20220228"],
        candidates,
    )

    assert targets["20220228"] == {}
    assert coverage["empty_months"] == 1


def test_piotroski_gate_rejects_quality_redundancy() -> None:
    """即使收益达标，与 Quality 高度重叠也不能作为独立候选。"""
    metric = {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.20,
        "annual_turnover": 4.0,
    }
    metrics = {name: dict(metric) for name in [*study.FOLDS, "full"]}

    gate = study.evaluate_gate(metrics, 0.90, {"passed": True})

    assert gate["passed"] is False
    assert gate["checks"]["quality_correlation_at_most_075"] is False
