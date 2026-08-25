"""2026-07-29策略研究决策备忘录测试。"""

from examples import research_campaign_20260729_decision_memo as memo


def test_dependency_chain_includes_strategy_and_execution_evidence() -> None:
    assert memo.campaign.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.factor_meta.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.common_mode.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.size_exposure.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.residual.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.capacity.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.alternative.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.premium_common.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.premium.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.sp500.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.sp500_equivalence.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.sp500_attribution.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.sp500_normalization.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.sp500_robustness.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.sp500_gold_vol.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.sp500_gold_failure.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.sp500_gold_statistics.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.trend.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.trend_failure.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.activity_data.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.activity.STRATEGY_ID in memo.DEPENDENCIES
    assert memo.activity_failure.EXPERIMENT_ID in memo.DEPENDENCIES
    assert memo.intraday.EXPERIMENT_ID in memo.DEPENDENCIES


def test_definition_never_changes_production_or_scheduler() -> None:
    definition = memo.RESEARCH_SPEC.definition

    assert definition["does_not_recompute_returns"] is True
    assert definition["does_not_modify_strategy_or_scheduler"] is True
    assert definition["reads_repository_metrics_only"] is True
