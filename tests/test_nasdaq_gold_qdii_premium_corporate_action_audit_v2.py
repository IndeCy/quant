"""QDII公司行动对齐审计测试。"""

from __future__ import annotations

import pandas as pd

from examples import (
    nasdaq_gold_qdii_premium_corporate_action_audit_v2 as audit,
)


def test_extreme_counter_uses_absolute_premium() -> None:
    frame = pd.DataFrame(
        {
            "close": [1.0, 2.0, 0.2],
            "nav": [1.0, 1.0, 1.0],
        }
    )

    assert audit.count_unexplained_extremes(frame) == 2


def test_cleaning_rule_is_fixed_without_return_information() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["rule_uses_returns"] is False
    assert definition["raw_database_mutation"] is False
    assert definition["does_not_override_source_gate"] is True
