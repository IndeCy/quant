"""日内强度失败归因测试。"""

from examples import intraday_strength_failure_attribution_audit as audit


def test_definition_forbids_post_hoc_factor_inversion() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert "invert_factor_after_observing_returns" in (
        definition["prohibited_followups"]
    )
    assert definition["does_not_override_source_rejection"] is True
    assert definition["return_recompute"] is False


def test_failure_requires_negative_periods_and_cost_not_total_explanation(
    tmp_path,
) -> None:
    metrics = {
        "period_metrics": {
            "train": {"annualized_return": -0.10},
            "validation": {"annualized_return": -0.12},
            "locked_test": {"annualized_return": -0.08},
            "full": {
                "annualized_return": -0.11,
                "max_drawdown": -0.90,
                "execution_cost_impact": 0.10,
            },
        },
        "annual_metrics": {
            "2024": {"annualized_return": -0.10},
            "2025": {"annualized_return": 0.05},
        },
        "data_quality": {"passed": True, "max_identity_error": 1e-15},
        "diagnostics": {"median_spearman_with_ret20": 0.50},
    }
    from runtime.paths import RuntimePaths

    result = audit.calculate(metrics, RuntimePaths(root=tmp_path))

    assert result["classification"] == (
        "ROBUST_ECONOMIC_SIGN_FAILURE_NOT_COST_ARTIFACT"
    )
    assert result["followup_variants_allowed"] is False
