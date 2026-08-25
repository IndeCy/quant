"""交易活跃度稳定性失败归因测试。"""

from examples import trading_activity_stability_failure_audit as audit


def test_forbidden_followups_cover_common_rescue_variants() -> None:
    forbidden = set(audit.RESEARCH_SPEC.definition["forbidden_followups"])

    assert {
        "change_factor_direction",
        "change_lookback",
        "change_top_n",
        "change_rebalance_frequency",
        "change_risk_overlay",
        "change_sample",
    } == forbidden


def test_audit_cannot_override_or_promote() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["reads_repository_metrics_only"] is True
    assert definition["does_not_change_source_gate"] is True
    assert definition["does_not_run_variants"] is True
    assert definition["does_not_promote_strategy"] is True
