"""Quality防守资产袖套来源归因测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from examples.defensive_sleeve_source_metrics import (
    build_fixed_budget_nav,
    classify_sleeve_dominance,
    variance_risk_contributions,
)


def test_variance_contributions_sum_to_one() -> None:
    """欧拉方差贡献占比必须严格加总为100%。"""
    returns = pd.DataFrame(
        {
            "core": [0.01, -0.01, 0.02, -0.015, 0.005],
            "gold": [0.003, 0.004, -0.002, 0.005, -0.001],
            "bond": [0.001, 0.001, 0.0, -0.001, 0.001],
        }
    )

    result = variance_risk_contributions(
        returns,
        {"core": 0.70, "gold": 0.15, "bond": 0.15},
    )

    assert sum(result["risk_contribution_share"].values()) == pytest.approx(1.0)


def test_fixed_budget_nav_uses_declared_weights() -> None:
    """固定预算净值应按声明权重组合每日收益。"""
    returns = pd.DataFrame(
        {
            "core": [0.10, 0.0],
            "gold": [0.0, 0.10],
            "bond": [0.0, 0.0],
        }
    )

    nav = build_fixed_budget_nav(
        returns,
        {"core": 0.70, "gold": 0.15, "bond": 0.15},
    )

    assert nav.iloc[0] == pytest.approx(1.07)
    assert nav.iloc[1] == pytest.approx(1.07 * 1.015)


def test_classifier_requires_both_risk_and_residual_dominance() -> None:
    """只有方差贡献和残差相关同时高时才判为核心支配。"""
    result = classify_sleeve_dominance(
        core_risk_share=0.85,
        actual_core_residual_correlation=0.95,
    )

    assert result["label"] == "CORE_RISK_DOMINANCE_CONFIRMED"
