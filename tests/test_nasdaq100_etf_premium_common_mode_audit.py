"""境内纳指100 ETF溢价共同模式审计测试。"""

from examples import nasdaq100_etf_premium_common_mode_audit as audit


def test_definition_does_not_claim_cause_or_authorize_substitution() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_infer_causal_quota_without_primary_data"] is True
    assert definition["does_not_authorize_lowest_premium_substitution"] is True
    assert definition["source_feasibility"] == audit.source.EXPERIMENT_ID


def test_common_mode_thresholds_are_frozen() -> None:
    checks = audit.RESEARCH_SPEC.definition["common_mode_checks"]

    assert checks["candidate_count_min"] == 10
    assert checks["share_above_5pct_min"] == 0.90
    assert checks["cross_section_median_premium_min"] == 0.08
    assert checks["cross_section_premium_range_max"] == 0.04
