"""Dividend Quality V1 研究脚本测试。"""

from __future__ import annotations

import pandas as pd

from examples.dividend_quality_v1 import (
    audit_dividend_data_sources,
    apply_dividend_quality_filters,
    score_dividend_quality_frame,
)


def test_score_dividend_quality_frame_uses_dividend_quality_and_cashflow() -> None:
    """红利质量分数应同时奖励股息、ROE/ROA和经营现金流质量。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "dividend_yield_proxy": [0.08, 0.02, 0.04],
            "roe": [15.0, 30.0, 10.0],
            "roa": [8.0, 12.0, 5.0],
            "ocf_to_or": [20.0, 5.0, 10.0],
        }
    )

    scored = score_dividend_quality_frame(frame)

    assert "dividend_quality_score" in scored.columns
    assert scored.iloc[0]["symbol"] == "A"
    assert scored["dividend_quality_score"].is_monotonic_decreasing


def test_apply_filters_requires_realistic_dividend_and_listing_quality() -> None:
    """基础清洗必须剔除ST、上市不足3年、无分红和高负债异常样本。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20260624"] * 4,
            "symbol": ["A", "B", "C", "D"],
            "name": ["正常", "*ST风险", "新股", "高负债"],
            "list_status": ["L", "L", "L", "L"],
            "list_date": ["20200101", "20200101", "20250101", "20200101"],
            "delist_date": [None, None, None, None],
            "st_name": [None, None, None, None],
            "end_date": ["20251231"] * 4,
            "dividend_yield_proxy": [0.04, 0.05, 0.05, 0.05],
            "payout_ratio": [0.3, 0.3, 0.3, 0.3],
            "dividend_consistency": [3, 3, 3, 3],
            "roe": [12.0] * 4,
            "roa": [6.0] * 4,
            "ocf_to_or": [15.0] * 4,
            "debt_to_assets": [50.0, 50.0, 50.0, 95.0],
        }
    )

    filtered = apply_dividend_quality_filters(frame)

    assert filtered["symbol"].tolist() == ["A"]


def test_audit_dividend_data_sources_reports_missing_standard_table() -> None:
    """没有独立分红表时，审计报告必须显式说明只能使用弱代理。"""
    audit = audit_dividend_data_sources({"income": ["comshare_payable_dvd", "f_ann_date"], "daily": ["close"]})

    assert audit["has_standard_dividend_table"] is False
    assert audit["has_income_dividend_proxy"] is True
    assert "comshare_payable_dvd" in audit["proxy_fields"]
