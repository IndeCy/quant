"""标普黄金波动目标失败归因测试。"""

from examples import sp500_gold_vol_target_failure_attribution_audit as audit


def test_expected_failures_are_frozen_and_specific() -> None:
    assert audit.EXPECTED_FAILED_CHECKS == {
        "oos_drawdown_within_20pct",
        "worst_fold_drawdown_within_20pct",
        "annual_turnover_below_15x",
    }


def test_definition_cannot_rescue_or_change_strategy() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["reads_repository_metrics_only"] is True
    assert definition["does_not_change_source_gate"] is True
    assert definition["does_not_change_parameters"] is True
    assert definition["does_not_promote_strategy"] is True
