"""标普500高溢价归一化重叠稳健性测试。"""

import numpy as np
import pandas as pd

from examples import sp500_premium_normalization_robustness_audit as audit


def test_non_overlapping_selection_respects_gap() -> None:
    high = pd.DataFrame(
        {
            "trade_date": [f"202501{day:02d}" for day in range(1, 31)],
            "forward_premium_effect": np.linspace(-0.03, 0.01, 30),
        },
        index=np.arange(30),
    )
    selected = audit.select_non_overlapping(high, 10)

    assert selected.index.tolist() == [0, 1, 2]
    assert selected["trade_date"].tolist() == [
        "20250101",
        "20250111",
        "20250121",
    ]


def test_bootstrap_is_deterministic_and_negative() -> None:
    values = np.array([-0.03, -0.02, -0.01, 0.005])

    first = audit.bootstrap_negative_median_probability(values, 1000, 7)
    second = audit.bootstrap_negative_median_probability(values, 1000, 7)

    assert first == second
    assert first > 0.80


def test_definition_controls_overlap_without_signal() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["overlap_controls"]["calendar_month_cluster_medians"]
    assert definition["does_not_define_a_trading_signal"] is True
    assert definition["does_not_authorize_instrument_substitution"] is True
