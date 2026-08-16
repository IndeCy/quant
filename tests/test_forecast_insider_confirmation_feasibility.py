"""业绩预告与重要股东增持交互覆盖审计测试。"""

from __future__ import annotations

import pandas as pd

from examples import forecast_insider_confirmation_feasibility_study as study


def test_monthly_overlap_applies_both_factor_validity_rules() -> None:
    """只有正向预告且净增持为正的同一股票才能进入交集。"""
    forecast = pd.DataFrame(
        [
            {
                "signal_date": "20220131",
                "symbol": "000001.SZ",
                "publish_date": "20220120",
                "forecast_type": "预增",
                "p_change_min": 10.0,
                "p_change_max": 20.0,
                "p_change_mid": 15.0,
            },
            {
                "signal_date": "20220131",
                "symbol": "000002.SZ",
                "publish_date": "20220120",
                "forecast_type": "预减",
                "p_change_min": -20.0,
                "p_change_max": -10.0,
                "p_change_mid": -15.0,
            },
        ]
    )
    insider = pd.DataFrame(
        [
            {
                "signal_date": "20220131",
                "symbol": "000001.SZ",
                "net_buy_ratio": 0.5,
            },
            {
                "signal_date": "20220131",
                "symbol": "000002.SZ",
                "net_buy_ratio": -0.5,
            },
        ]
    )

    result = study.build_monthly_overlap(["20220131"], forecast, insider)

    assert result.iloc[0]["overlap_count"] == 1
    assert result.iloc[0]["overlap_symbols"] == "000001.SZ"


def test_feasibility_rejects_sparse_locked_period() -> None:
    """历史有少量交集但锁定期无法稳定构造 Top10 时必须拒绝。"""
    monthly = pd.DataFrame(
        [
            {
                "signal_date": f"{year}0131",
                "year": year,
                "overlap_count": 1,
                "top10_constructible": False,
            }
            for year in range(2015, 2027)
        ]
    )

    result = study.evaluate_feasibility(monthly, "20260724")

    assert result["passed"] is False
    assert result["decision"] == "REJECTED_BEFORE_BACKTEST"
    assert result["checks"]["locked_top10_constructible_share"] is False


def test_feasibility_passes_frozen_coverage_gates() -> None:
    """覆盖数量、年份和锁定期都满足时才允许进入固定回测。"""
    dates = pd.date_range("2015-01-31", "2026-07-31", freq="ME")
    monthly = pd.DataFrame(
        {
            "signal_date": dates.strftime("%Y%m%d"),
            "year": dates.year,
            "overlap_count": 12,
            "top10_constructible": True,
        }
    )

    result = study.evaluate_feasibility(monthly, "20260724")

    assert result["passed"] is True
    assert result["decision"] == "CONTINUE_TO_FIXED_BACKTEST"
