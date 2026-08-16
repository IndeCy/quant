"""纳指黄金与直接标普同资金容量比较测试。"""

import pandas as pd

from examples import nasdaq_gold_sp500_capacity_comparison_audit as audit


def test_definition_uses_equal_capital_and_preserves_source_gates() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert audit.CAPITAL == 1_000_000.0
    assert audit.PORTFOLIOS["sp500_direct"] == {audit.base.SP500: 1.0}
    assert definition["does_not_override_either_source_gate"] is True
    assert definition["source_capacity_audit"] == (
        audit.capacity.EXPERIMENT_ID
    )


def test_binding_participation_is_maximum_component() -> None:
    bars = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-07-28")] * 3,
            "symbol": [audit.base.NASDAQ, audit.base.GOLD, audit.base.SP500],
            "amount_cny": [60_000_000.0, 200_000_000.0, 50_000_000.0],
        }
    )

    result = audit.build_binding_participation(bars)
    candidate = result[
        result["portfolio"].eq("nasdaq_gold_60_40")
    ].iloc[0]
    benchmark = result[result["portfolio"].eq("sp500_direct")].iloc[0]

    assert candidate["binding_symbol"] == audit.base.NASDAQ
    assert candidate["binding_participation"] == 0.01
    assert benchmark["binding_participation"] == 0.02
