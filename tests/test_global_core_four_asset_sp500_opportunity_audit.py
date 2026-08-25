from __future__ import annotations

import pandas as pd

from examples import global_core_four_asset_sp500_opportunity_audit as audit


def test_definition_does_not_override_original_gate() -> None:
    assert audit.RESEARCH_SPEC.definition["override_original_gate"] is False


def test_block_bootstrap_is_deterministic() -> None:
    returns = pd.DataFrame(
        {
            "candidate": [0.001 * ((i % 5) - 2) for i in range(80)],
            "sp500": [0.001 * ((i % 7) - 3) for i in range(80)],
        }
    )

    left = audit.block_bootstrap_lifts(
        returns,
        samples=20,
        block_days=5,
        seed=4,
    )
    right = audit.block_bootstrap_lifts(
        returns,
        samples=20,
        block_days=5,
        seed=4,
    )

    pd.testing.assert_frame_equal(left, right)
