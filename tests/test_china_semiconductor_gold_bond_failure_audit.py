"""半导体黄金国债失败统计审计测试。"""

from examples import china_semiconductor_gold_bond_failure_audit as audit


def test_definition_requires_exact_original_failures() -> None:
    assert sorted(
        audit.RESEARCH_SPEC.definition["original_failed_checks_required"]
    ) == [
        "all_three_folds_positive",
        "sharpe_shortfall_vs_global_within_010",
    ]


def test_audit_never_overrides_original_gate() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["original_gate_override"] is False
    assert definition["bootstrap"]["samples"] == 10_000
    assert definition["bootstrap"]["block_days"] == 20
