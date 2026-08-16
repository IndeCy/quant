"""标普黄金波动目标统计优势审计测试。"""

from examples import sp500_gold_vol_target_statistical_audit as audit


def test_control_uses_same_vol_target_mechanism() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["control"] == audit.source.VOL_CONTROL_ID
    assert definition["candidate"] == audit.source.EXPERIMENT_ID
    assert definition["bootstrap"]["paired"] is True


def test_statistical_audit_cannot_override_rejection() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_override_source_rejection"] is True
    assert definition["does_not_change_parameters"] is True
