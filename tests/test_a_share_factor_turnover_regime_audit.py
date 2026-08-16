"""A股因子换手分层锁定期存活审计测试。"""

from examples import a_share_factor_turnover_regime_audit as audit


def test_turnover_buckets_are_fixed_and_exhaustive() -> None:
    assert audit.classify_turnover(8.0) == "low_le_8x"
    assert audit.classify_turnover(8.01) == "medium_8_to_15x"
    assert audit.classify_turnover(15.0) == "medium_8_to_15x"
    assert audit.classify_turnover(15.01) == "high_gt_15x"


def test_definition_is_descriptive_and_does_not_reclassify() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["descriptive_only"] is True
    assert definition["does_not_reclassify_source_strategies"] is True
    assert definition["source_meta_audit"] == audit.source.EXPERIMENT_ID
