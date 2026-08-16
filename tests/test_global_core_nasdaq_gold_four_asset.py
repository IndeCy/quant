from __future__ import annotations

import pytest

from examples import global_core_nasdaq_gold_four_asset_study as study


def test_weights_are_exactly_derived_from_two_equal_sleeves() -> None:
    assert sum(study.ASSET_WEIGHTS.values()) == pytest.approx(1.0)
    assert study.ASSET_WEIGHTS[study.NASDAQ] == pytest.approx(0.30)
    assert study.ASSET_WEIGHTS[study.SP500] == pytest.approx(1 / 6)
    assert study.ASSET_WEIGHTS[study.GOLD] == pytest.approx(11 / 30)
    assert study.ASSET_WEIGHTS[study.BOND] == pytest.approx(1 / 6)


def test_definition_has_no_weight_grid_and_requires_passed_growth_v3() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["portfolio"]["weight_grid"] is False
    assert (
        definition["dependencies"]["growth_sleeve_standalone_outcome_required"]
        == "PASSED_RESEARCH_GATE"
    )
    assert definition["parameters_fixed_before_combined_return_loading"] is True
