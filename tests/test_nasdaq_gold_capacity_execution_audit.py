"""纳指黄金60/40资金容量与整手审计测试。"""

import pandas as pd

from examples import nasdaq_gold_capacity_execution_audit as audit


def test_definition_freezes_source_weights_and_capacity_gates() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert audit.WEIGHTS == {audit.base.NASDAQ: 0.60, audit.base.GOLD: 0.40}
    assert definition["source_strategy"] == audit.base.EXPERIMENT_ID
    assert definition["capacity"]["amount_multiplier"] == 1_000.0
    assert definition["lot_rounding"]["lot_size"] == 100
    assert definition["does_not_override_source_gate"] is True


def test_whole_lot_cases_leave_cash_and_hold_both_assets() -> None:
    latest = pd.DataFrame(
        {
            "symbol": audit.SYMBOLS,
            "close": [2.50, 8.00],
        }
    ).set_index("symbol")

    cases = audit.build_lot_cases(latest)

    assert cases["held_assets"].eq(2).all()
    assert cases["cash"].ge(0).all()
    assert cases["tracking_total_variation"].ge(0).all()


def test_capacity_checks_apply_one_and_five_million_hurdles() -> None:
    capacity = pd.DataFrame(
        {
            "valid_days": [1900, 1900],
            "capital_1000000_p90_participation": [0.005, 0.009],
            "capital_1000000_latest_participation": [0.004, 0.008],
            "capital_5000000_median_participation": [0.006, 0.009],
            "capital_5000000_p90_participation": [0.015, 0.019],
        }
    )
    lots = pd.DataFrame(
        {
            "capital": [100_000.0, 500_000.0],
            "held_assets": [2, 2],
            "tracking_total_variation": [0.004, 0.001],
        }
    )

    checks = audit.evaluate_checks(capacity, lots, staleness_days=1)

    assert all(checks.values())
    capacity.loc[0, "capital_5000000_p90_participation"] = 0.021
    checks = audit.evaluate_checks(capacity, lots, staleness_days=1)
    assert checks["five_million_p90_participation_within_2pct"] is False
