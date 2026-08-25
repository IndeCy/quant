"""纳指黄金容量失败分期归因测试。"""

import pandas as pd

from examples import nasdaq_gold_capacity_failure_attribution_audit as audit


def test_definition_preserves_source_failure_and_fixed_periods() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["source_capacity_audit"] == audit.source.EXPERIMENT_ID
    assert definition["does_not_override_source_capacity_failure"] is True
    assert definition["does_not_restate_historical_returns"] is True
    assert audit.PERIODS["2019"] == ("20190101", "20191231")
    assert audit.PERSISTENCE_MONTHS == 12


def test_persistent_recovery_requires_consecutive_months() -> None:
    rolling = pd.DataFrame(
        {
            "trade_date": [f"2024{month:02d}28" for month in range(1, 13)],
            "rolling_p90_participation": [0.009] * 12,
        }
    )

    assert (
        audit.persistent_recovery_date(
            rolling,
            threshold=0.01,
            months=12,
        )
        == "20240128"
    )
    rolling.loc[5, "rolling_p90_participation"] = 0.011
    assert (
        audit.persistent_recovery_date(
            rolling,
            threshold=0.01,
            months=12,
        )
        is None
    )
