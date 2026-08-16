from __future__ import annotations

import pandas as pd

from examples import limit_event_sentiment_allocation_study as study


def test_definition_freezes_threshold_and_weights_before_returns() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["state"]["threshold_search"] is False
    assert definition["parameters_fixed_before_return_loading"] is True
    assert sum(definition["allocation"]["risk_on"].values()) == 1.0
    assert sum(definition["allocation"]["risk_off"].values()) == 1.0


def test_sentiment_targets_switch_at_fixed_half_threshold() -> None:
    weekly = pd.DataFrame(
        {
            "trade_date": ["20260109", "20260116"],
            "sentiment_5d": [0.49, 0.50],
        }
    )

    targets = study.build_sentiment_targets(weekly)

    assert study.EQUITY not in targets["20260109"]
    assert targets["20260116"][study.EQUITY] == 0.60
    assert study.count_state_switches(targets) == 1
