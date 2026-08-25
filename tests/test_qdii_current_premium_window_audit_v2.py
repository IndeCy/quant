"""QDII当前折溢价窗口归因测试。"""

import pandas as pd

from examples import qdii_current_premium_window_audit_v2 as audit


def test_definition_inherits_source_and_keeps_realtime_caveat() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["source_monitoring_audit"] == audit.source.EXPERIMENT_ID
    assert definition["does_not_replace_realtime_iopv"] is True
    assert definition["does_not_override_source_gate"] is True
    assert definition["frozen_gate"]["weighted_normalization_shock_floor"] == -0.06


def test_matched_premiums_require_same_symbol_and_date() -> None:
    nav = pd.DataFrame(
        {
            "symbol": ["159941.SZ", "159941.SZ"],
            "end_date": ["20260724", "20260727"],
            "unit_nav": [1.40, 1.42],
        }
    )
    prices = pd.DataFrame(
        {
            "symbol": ["159941.SZ", "159941.SZ"],
            "trade_date": ["20260724", "20260727"],
            "close": [1.47, 1.562],
        }
    )

    matched = audit.build_matched_premiums(nav, prices)

    assert matched["premium"].round(3).tolist() == [0.050, 0.100]
