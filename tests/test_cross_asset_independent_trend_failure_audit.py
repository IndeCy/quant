"""五资产独立趋势数据门禁失败归因测试。"""

import pandas as pd

from examples import cross_asset_independent_trend_failure_audit as audit


def test_compare_dates_marks_upstream_only_rows() -> None:
    local = pd.DataFrame(
        {
            "symbol": ["A", "A"],
            "trade_date": ["20260727", "20260728"],
        }
    )
    upstream = pd.DataFrame(
        {
            "symbol": ["A", "A", "B"],
            "trade_date": ["20260727", "20260728", "20260728"],
        }
    )
    result = audit.compare_dates(local, upstream)

    missing = result[result["local_missing"]]
    assert missing[["symbol", "trade_date"]].values.tolist() == [
        ["B", "20260728"]
    ]


def test_definition_forbids_patch_bypass_and_backtest() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_patch_local_database"] is True
    assert definition["does_not_bypass_feasibility_gate"] is True
    assert definition["does_not_run_strategy_backtest"] is True
