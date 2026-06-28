import pandas as pd
import pytest

from examples.quality_portfolio_construction_study import (
    apply_industry_cap,
    inverse_volatility_weights,
)


def test_apply_industry_cap_limits_known_industry_to_twenty_percent():
    frame = pd.DataFrame(
        {
            "symbol": [f"A{i}" for i in range(10)] + [f"B{i}" for i in range(10)],
            "industry_level1": ["行业A"] * 10 + ["行业B"] * 10,
            "quality_score": list(range(20, 0, -1)),
        }
    )

    selected = apply_industry_cap(frame, top_n=10, cap=0.2)

    assert selected["industry_level1"].value_counts().max() <= 2


def test_inverse_volatility_weights_favor_lower_volatility():
    frame = pd.DataFrame({"symbol": ["LOW", "HIGH"], "vol60": [0.1, 0.2]})

    weights = inverse_volatility_weights(frame)

    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["LOW"] == pytest.approx(2 / 3)
    assert weights["HIGH"] == pytest.approx(1 / 3)
