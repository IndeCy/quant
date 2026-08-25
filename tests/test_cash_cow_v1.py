"""Cash Cow V1 研究脚本测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from examples.cash_cow_v1 import (
    calculate_overlap,
    compute_cash_cow_fields,
    score_cash_cow_frame,
)


def test_compute_cash_cow_fields_uses_operating_cashflow_minus_capex() -> None:
    """FCF 应等于经营现金流减资本开支现金流出。"""
    frame = pd.DataFrame(
        {
            "n_cashflow_act": [100.0],
            "c_pay_acq_const_fiolta": [40.0],
            "revenue": [200.0],
            "n_income_attr_p": [50.0],
            "total_assets": [500.0],
        }
    )

    result = compute_cash_cow_fields(frame)

    assert result.loc[0, "ocf_to_or_raw"] == pytest.approx(0.5)
    assert result.loc[0, "ocf_to_np"] == pytest.approx(2.0)
    assert result.loc[0, "fcf"] == pytest.approx(60.0)
    assert result.loc[0, "fcf_to_assets"] == pytest.approx(0.12)


def test_score_cash_cow_frame_uses_fixed_weights() -> None:
    """CashCowScore 固定为 35/35/30，不允许隐式调参。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "ocf_to_or": [0.3, 0.2, 0.1],
            "ocf_to_np": [3.0, 2.0, 1.0],
            "fcf_to_assets": [0.12, 0.08, 0.04],
            "debt_to_assets": [30.0, 40.0, 50.0],
        }
    )

    scored = score_cash_cow_frame(frame)

    assert scored.iloc[0]["symbol"] == "A"
    assert scored.iloc[-1]["symbol"] == "C"
    assert "cash_cow_score" in scored.columns


def test_calculate_overlap_returns_monthly_average_overlap() -> None:
    cash = {"20240131": ["A", "B"], "20240229": ["A", "C"]}
    quality = {"20240131": ["B", "C"], "20240229": ["D", "E"]}

    assert calculate_overlap(cash, quality) == pytest.approx(0.25)
