from __future__ import annotations

from examples import research_campaign_20260729_meta_audit as audit


def test_definition_never_recomputes_or_overrides_returns() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_recompute_returns"] is True
    assert definition["does_not_override_decisions"] is True


def test_count_values_is_deterministic() -> None:
    rows = [{"outcome": "B"}, {"outcome": "A"}, {"outcome": "B"}]

    assert audit.count_values(rows, "outcome") == {"A": 1, "B": 2}
