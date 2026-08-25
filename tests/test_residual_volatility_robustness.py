"""低特质波动稳健性与Beta归因测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from examples.residual_volatility_robustness_metrics import (
    classify_return_source,
    market_regression_attribution,
    summarize_market_attribution,
)


def test_market_regression_recovers_known_beta_and_alpha() -> None:
    """合成策略为固定日Alpha加0.5倍市场时应恢复对应回归系数。"""
    index = pd.bdate_range("2024-01-01", periods=300)
    market_returns = pd.Series(
        [0.01, -0.008, 0.004, -0.003, 0.006] * 60,
        index=index,
    )
    strategy_returns = 0.0001 + 0.5 * market_returns
    strategy = (1.0 + strategy_returns).cumprod()
    benchmark = (1.0 + market_returns).cumprod()

    result = market_regression_attribution(strategy, benchmark)

    assert result["beta"] == pytest.approx(0.5, abs=1e-10)
    assert result["annualized_alpha"] == pytest.approx(
        (1.0001**252) - 1,
        rel=1e-8,
    )


def test_market_attribution_summary_counts_positive_alpha() -> None:
    """窗口汇总必须分别统计Alpha广度和Beta上界。"""
    summary = summarize_market_attribution(
        {
            "A": {
                "annualized_alpha": 0.03,
                "beta": 0.7,
                "up_capture": 0.8,
                "down_capture": 0.5,
            },
            "B": {
                "annualized_alpha": -0.01,
                "beta": 0.9,
                "up_capture": 0.7,
                "down_capture": 0.6,
            },
        }
    )

    assert summary["positive_alpha_share"] == 0.5
    assert summary["maximum_beta"] == 0.9


def test_classifier_rejects_high_quality_correlation_as_independent() -> None:
    """Alpha和防御性成立但高度相关时只能判为共同防御溢价。"""
    result = classify_return_source(
        full_attribution={
            "annualized_alpha": 0.04,
            "beta": 0.7,
            "up_capture": 0.8,
            "down_capture": 0.5,
        },
        period_summary={"positive_alpha_share": 0.75},
        quality_correlation=0.82,
    )

    assert result["label"] == "SHARED_DEFENSIVE_PREMIUM"
