import pandas as pd
import pytest

from examples.quality_drawdown_forensics import concentration_metrics, position_loss_contributions


def test_concentration_metrics_calculates_top_weights_and_hhi():
    weights = pd.Series([0.4, 0.3, 0.2, 0.1])

    metrics = concentration_metrics(weights)

    assert metrics["top5_weight"] == pytest.approx(1.0)
    assert metrics["top10_weight"] == pytest.approx(1.0)
    assert metrics["hhi"] == pytest.approx(0.3)


def test_position_loss_contributions_uses_start_weight_times_loss():
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B"],
            "weight": [0.6, 0.4],
            "start_price": [10.0, 20.0],
            "end_price": [5.0, 18.0],
        }
    )

    result = position_loss_contributions(frame)

    row_a = result[result["symbol"].eq("A")].iloc[0]
    assert row_a["period_return"] == pytest.approx(-0.5)
    assert row_a["loss_contribution"] == pytest.approx(0.3)
