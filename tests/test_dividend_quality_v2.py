"""Dividend Quality V2 测试。"""

from __future__ import annotations

import pandas as pd

from examples.dividend_quality_v2 import build_trailing_dividend_asof, score_dividend_quality_v2_frame


def test_trailing_dividend_asof_uses_only_ex_date_visible_records() -> None:
    """股息率只能使用除息日已发生的实施分红，不能使用未来实施记录。"""
    signal_dates = ["20260610", "20260630"]
    dividends = pd.DataFrame(
        [
            {"ts_code": "AAA.SZ", "ex_date": "20260612", "cash_div_tax": 0.5, "div_proc": "实施"},
            {"ts_code": "AAA.SZ", "ex_date": "20260710", "cash_div_tax": 1.0, "div_proc": "实施"},
            {"ts_code": "BBB.SZ", "ex_date": None, "cash_div_tax": 2.0, "div_proc": "预案"},
        ]
    )
    prices = pd.DataFrame(
        [
            {"signal_date": "20260610", "symbol": "AAA.SZ", "close": 10.0},
            {"signal_date": "20260630", "symbol": "AAA.SZ", "close": 10.0},
            {"signal_date": "20260630", "symbol": "BBB.SZ", "close": 10.0},
        ]
    )

    result = build_trailing_dividend_asof(signal_dates, dividends, prices)

    assert result[(result["signal_date"] == "20260610") & (result["symbol"] == "AAA.SZ")].empty
    visible = result[(result["signal_date"] == "20260630") & (result["symbol"] == "AAA.SZ")].iloc[0]
    assert visible["trailing_dividend_yield"] == 0.05
    assert "BBB.SZ" not in set(result["symbol"])


def test_score_dividend_quality_v2_prefers_real_dividend_with_quality() -> None:
    """V2 分数应使用真实 trailing dividend yield 加质量和现金流。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B"],
            "trailing_dividend_yield": [0.06, 0.02],
            "roe": [12.0, 30.0],
            "roa": [6.0, 10.0],
            "ocf_to_or": [20.0, 5.0],
        }
    )

    scored = score_dividend_quality_v2_frame(frame)

    assert scored.iloc[0]["symbol"] == "A"
    assert "dividend_quality_score" in scored.columns
