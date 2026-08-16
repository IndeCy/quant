from __future__ import annotations

from examples import global_defensive_margin_flow_satellite_study as study


def test_definition_hard_caps_rejected_satellite_without_grid() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["dependencies"]["satellite_standalone_outcome_required"] == "REJECTED"
    assert definition["sleeves"]["satellite"]["hard_cap"] == 0.10
    assert definition["sleeves"]["satellite"]["standalone_not_promoted"] is True
    assert definition["allocation"]["weight_grid"] is False
    assert definition["parameters_fixed_before_combined_return_loading"] is True
