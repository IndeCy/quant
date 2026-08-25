from __future__ import annotations

import pandas as pd

from examples import global_defensive_margin_flow_correlation_audit as audit


def test_definition_forbids_original_gate_override() -> None:
    assert audit.RESEARCH_SPEC.definition["override_original_gate"] is False


def test_block_bootstrap_is_deterministic() -> None:
    returns = pd.DataFrame(
        {
            "candidate": [0.001 * ((i % 5) - 2) for i in range(80)],
            "quality": [0.001 * ((i % 7) - 3) for i in range(80)],
        }
    )

    left = audit.block_bootstrap_correlations(
        returns,
        samples=20,
        block_days=5,
        seed=3,
    )
    right = audit.block_bootstrap_correlations(
        returns,
        samples=20,
        block_days=5,
        seed=3,
    )

    pd.testing.assert_frame_equal(left, right)
