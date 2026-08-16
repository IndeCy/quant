from __future__ import annotations

import pandas as pd

from examples import margin_flow_breadth_allocation_study as study


def test_definition_freezes_majority_threshold_without_grid() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["state"]["risk_on_if_greater_or_equal"] == 0.50
    assert definition["state"]["threshold_search"] is False
    assert definition["parameters_fixed_before_return_loading"] is True


def test_targets_switch_at_majority_threshold() -> None:
    monthly = pd.DataFrame(
        {
            "signal_date": ["20260130", "20260227"],
            "margin_breadth": [0.49, 0.50],
        }
    )

    targets = study.build_breadth_targets(monthly)

    assert study.EQUITY not in targets["20260130"]
    assert targets["20260227"][study.EQUITY] == 0.60
    assert study.count_state_switches(targets) == 1
