"""Cash Cow V1.5 修复验证测试。"""

from __future__ import annotations

import pandas as pd

from examples.cash_cow_v15 import (
    apply_industry_cap,
    apply_v15_filters,
    score_cash_cow_v15_frame,
)


def test_v15_filters_remove_low_margin_and_unstable_cashflow() -> None:
    """净利润率陷阱和3年现金流稳定性必须同时过滤。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "n_income_attr_p": [10.0, 1.0, 10.0],
            "revenue": [100.0, 1000.0, 100.0],
            "ocf_to_np": [5.0, 100.0, 5.0],
            "ocf_positive_years_3": [2, 2, 1],
            "fcf_positive_years_3": [2, 2, 2],
            "ocf_to_or": [0.2, 0.9, 0.3],
            "fcf_to_assets": [0.1, 0.2, 0.1],
            "debt_to_assets": [30.0, 30.0, 30.0],
        }
    )

    filtered = apply_v15_filters(frame)

    assert filtered["symbol"].tolist() == ["A"]


def test_v15_score_does_not_use_ocf_to_np_as_core_factor() -> None:
    """V1.5 核心打分只使用 OCF_TO_OR 和 FCF_TO_ASSETS。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B"],
            "ocf_to_or": [0.2, 0.1],
            "fcf_to_assets": [0.2, 0.1],
            "ocf_to_np": [1.0, 1000.0],
        }
    )

    scored = score_cash_cow_v15_frame(frame)

    assert scored.iloc[0]["symbol"] == "A"
    assert "ocf_to_np_z" not in scored.columns


def test_apply_industry_cap_limits_each_industry_to_20_percent() -> None:
    """Top20 单行业上限20%，即每个行业最多4只。"""
    frame = pd.DataFrame(
        {
            "symbol": [f"A{i}" for i in range(10)] + [f"B{i}" for i in range(10)],
            "industry_level1": ["地产"] * 10 + ["科技"] * 10,
            "cash_cow_score": list(range(20, 0, -1)),
        }
    )

    selected = apply_industry_cap(frame, top_n=20, cap=0.2)

    assert selected["industry_level1"].value_counts().max() == 4
