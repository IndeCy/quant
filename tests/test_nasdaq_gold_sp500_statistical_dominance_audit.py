"""纳指黄金相对标普统计审计测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from examples import nasdaq_gold_sp500_statistical_dominance_audit as audit


def test_paired_bootstrap_is_deterministic_and_preserves_sample_count() -> None:
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {
            "candidate": rng.normal(0.0005, 0.01, 300),
            "sp500": rng.normal(0.0003, 0.01, 300),
        }
    )

    first = audit.paired_block_bootstrap(
        frame,
        samples=20,
        block_days=10,
        seed=9,
    )
    second = audit.paired_block_bootstrap(
        frame,
        samples=20,
        block_days=10,
        seed=9,
    )

    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 20


def test_performance_comparison_rewards_higher_return_and_lower_drawdown() -> None:
    candidate = np.repeat(0.0005, 252)
    sp500 = np.array([0.001] * 251 + [-0.20])

    result = audit.compare_metrics(candidate, sp500)

    assert result["return_lift"] > 0
    assert result["drawdown_improvement"] > 0


def test_definition_freezes_bootstrap_and_does_not_override_source() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["bootstrap"]["samples"] == 10_000
    assert definition["bootstrap"]["block_days"] == 20
    assert definition["does_not_override_source_gate"] is True
