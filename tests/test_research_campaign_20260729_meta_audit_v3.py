"""含容量与当前溢价证据的最终元审计测试。"""

from examples import research_campaign_20260729_meta_audit_v3 as audit


def test_campaign_is_unique_and_superset_of_v2() -> None:
    ids = [
        experiment_id
        for values in audit.CAMPAIGN.values()
        for experiment_id in values
    ]
    v2_ids = {
        experiment_id
        for values in audit.v2.CAMPAIGN.values()
        for experiment_id in values
    }

    assert len(ids) == len(set(ids))
    assert set(ids).issuperset(v2_ids)
    assert audit.v2.EXPERIMENT_ID in ids


def test_current_risk_audits_are_explicitly_included() -> None:
    audits = set(audit.CAMPAIGN["audit"])

    assert {
        "nasdaq_gold_60_40_capacity_execution_audit_v1",
        "qdii_current_nav_monitoring_audit_v1",
        "qdii_current_premium_window_audit_v2",
    }.issubset(audits)


def test_sp500_execution_and_equivalence_are_included() -> None:
    assert (
        "sp500_gold_60_40_vol_target_12_v1"
        in audit.CAMPAIGN["strategy"]
    )
    assert (
        "sp500_domestic_etf_execution_feasibility_v1"
        in audit.CAMPAIGN["feasibility"]
    )
    assert (
        "sp500_etf_513650_513500_instrument_equivalence_audit_v1"
        in audit.CAMPAIGN["audit"]
    )
    assert (
        "sp500_etf_premium_tracking_attribution_audit_v1"
        in audit.CAMPAIGN["audit"]
    )
    assert (
        "sp500_etf_premium_normalization_risk_audit_v1"
        in audit.CAMPAIGN["audit"]
    )
    assert (
        "sp500_premium_normalization_robustness_audit_v1"
        in audit.CAMPAIGN["audit"]
    )
    assert (
        "sp500_gold_vol_target_failure_attribution_audit_v1"
        in audit.CAMPAIGN["audit"]
    )
    assert (
        "sp500_gold_vol_target_statistical_audit_v1"
        in audit.CAMPAIGN["audit"]
    )


def test_independent_trend_data_block_is_included() -> None:
    assert (
        "cross_asset_independent_trend_data_feasibility_v1"
        in audit.CAMPAIGN["feasibility"]
    )
    assert (
        "cross_asset_independent_trend_feasibility_failure_audit_v1"
        in audit.CAMPAIGN["audit"]
    )


def test_trading_activity_candidate_and_failure_are_included() -> None:
    assert "trading_activity_stability_v1" in audit.CAMPAIGN["strategy"]
    assert (
        "trading_activity_stability_data_feasibility_v1"
        in audit.CAMPAIGN["feasibility"]
    )
    assert (
        "trading_activity_stability_failure_attribution_audit_v1"
        in audit.CAMPAIGN["audit"]
    )


def test_definition_does_not_recompute_or_override() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_recompute_returns"] is True
    assert definition["does_not_override_decisions"] is True
