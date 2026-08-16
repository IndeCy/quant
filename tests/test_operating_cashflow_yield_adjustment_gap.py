"""经营现金流收益率复权缺口诊断测试。"""

from __future__ import annotations

import pandas as pd

from examples.operating_cashflow_yield_adjustment_gap_metrics import (
    diagnose_adjustment_gaps,
)


def test_gap_diagnosis_confirms_recoverable_lookback_defect() -> None:
    """统一视图缺失但完整同源历史可恢复时应判为回看截断。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20150130", "20150227"],
            "symbol": ["000001.SZ", "000002.SZ"],
            "f_ann_date": ["20140307", "20140420"],
            "current_adj_factor": [2.0, 3.0],
            "report_adj_factor": [None, None],
            "full_report_adj_factor": [1.9, 2.8],
        }
    )

    result = diagnose_adjustment_gaps(frame)

    assert result["passed"] is True
    assert result["recovered_rows"] == 2
    assert result["unresolved_rows"] == 0
    assert result["decision"] == "DATA_LAYER_LOOKBACK_DEFECT_CONFIRMED"


def test_gap_diagnosis_rejects_unresolved_source_gap() -> None:
    """完整历史仍不存在复权因子时不得宣称可修。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20150130"],
            "symbol": ["000001.SZ"],
            "f_ann_date": ["20140307"],
            "current_adj_factor": [2.0],
            "report_adj_factor": [None],
            "full_report_adj_factor": [None],
        }
    )

    result = diagnose_adjustment_gaps(frame)

    assert result["passed"] is False
    assert result["decision"] == "GENUINE_ADJUSTMENT_GAPS_REMAIN"
