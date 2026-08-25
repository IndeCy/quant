"""纳指黄金容量恢复后表现审计测试。"""

import pandas as pd

from examples import nasdaq_gold_post_capacity_recovery_audit as audit


def test_definition_anchors_sample_to_capacity_not_returns() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["start_selection_uses_returns"] is False
    assert definition["does_not_override_source_gate"] is True
    assert definition["does_not_rehabilitate_pre_recovery_backtest"] is True
    assert definition["source_capacity_attribution"] == (
        audit.capacity.EXPERIMENT_ID
    )


def test_gate_requires_all_fixed_performance_and_probability_checks() -> None:
    original = {
        "return_lift": 0.02,
        "sharpe_lift": 0.20,
        "drawdown_improvement": 0.03,
    }
    probabilities = {
        "return_lift_at_least_05pct": 0.80,
        "sharpe_lift_at_least_005": 0.75,
        "drawdown_improvement_positive": 0.90,
    }
    years = pd.DataFrame(
        {
            "candidate_return": [0.10, 0.15],
            "sp500_return": [0.08, 0.09],
        }
    )

    assert all(audit.evaluate_checks(original, probabilities, years).values())
    probabilities["return_lift_at_least_05pct"] = 0.69
    checks = audit.evaluate_checks(original, probabilities, years)
    assert checks["return_lift_probability_at_least_70pct"] is False
