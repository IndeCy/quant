"""A股因子低换手优势统计审计测试。"""

import numpy as np

from examples import a_share_factor_turnover_statistical_audit as audit


def test_definition_never_claims_alpha_or_overrides_sources() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_establish_alpha"] is True
    assert definition["does_not_override_source_decisions"] is True
    assert definition["bootstrap"]["samples"] == 10_000


def test_bootstrap_is_deterministic_and_preserves_group_sizes() -> None:
    low = np.array([0.01, 0.02, 0.03])
    high = np.array([-0.03, -0.02, -0.01])

    first = audit.bootstrap_median_difference(
        low,
        high,
        samples=100,
        seed=7,
    )
    second = audit.bootstrap_median_difference(
        low,
        high,
        samples=100,
        seed=7,
    )

    assert first.equals(second)
    assert len(first) == 100
    assert first["median_difference"].gt(0).all()
