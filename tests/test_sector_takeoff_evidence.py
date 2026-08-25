"""板块起飞前证据研究的点时性和评分测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from examples.sector_candidate_confirmation_audit import summarize_themes
from examples.sector_takeoff_case_timeline_audit import summarize_cases
from examples.sector_takeoff_evidence_support import (
    build_monthly_sector_samples,
    merge_recent_breadth,
    score_sector_samples,
)
from examples.sector_takeoff_path_audit import classify_states


def _daily_panel(periods: int = 320, boards: int = 12) -> pd.DataFrame:
    dates = pd.bdate_range("2021-01-04", periods=periods)
    rows = []
    for board in range(boards):
        growth = 0.0005 + board * 0.00008
        for index, trade_date in enumerate(dates):
            rows.append(
                {
                    "ts_code": f"BK{board:04d}.DC",
                    "trade_date": trade_date.strftime("%Y%m%d"),
                    "close": 100.0 * (1.0 + growth) ** index,
                    "amount": 1_000_000.0 * (1.0 + board / 20.0)
                    * (1.0 + index / 1000.0),
                    "turnover_rate": 1.0 + board / 20.0 + index / 5000.0,
                    "category": "概念板块",
                }
            )
    return pd.DataFrame(rows)


def _benchmark(periods: int = 320) -> pd.DataFrame:
    dates = pd.bdate_range("2021-01-04", periods=periods)
    return pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "close": 100.0 * (1.0004 ** np.arange(periods)),
        }
    )


def test_monthly_features_do_not_change_when_future_prices_change() -> None:
    daily = _daily_panel()
    cutoff = "20211231"
    original = build_monthly_sector_samples(daily, _benchmark())
    changed = daily.copy()
    changed.loc[changed["trade_date"].gt(cutoff), "close"] *= 3.0
    revised = build_monthly_sector_samples(changed, _benchmark())

    feature_columns = [
        "ret_20",
        "ret_60",
        "ret_120",
        "relative_ret_60",
        "return_acceleration",
        "amount_ratio_20_120",
        "turnover_ratio_20_120",
        "distance_to_high_120",
        "evidence_score",
    ]
    left = original[
        original["trade_date"].le(cutoff)
    ].set_index(["ts_code", "trade_date"])
    right = revised[
        revised["trade_date"].le(cutoff)
    ].set_index(["ts_code", "trade_date"])
    pd.testing.assert_frame_equal(
        left[feature_columns],
        right[feature_columns],
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_score_applies_frozen_maturity_penalty() -> None:
    rows = []
    for index in range(10):
        rows.append(
            {
                "trade_date": "20260130",
                "relative_ret_60": float(index),
                "return_acceleration": float(index),
                "amount_ratio_20_120": float(index + 1),
                "turnover_ratio_20_120": 1.0 + index / 10.0,
                "distance_to_high_120": -0.1 + index / 100.0,
                "ret_60": 0.1,
                "ret_120": 0.2,
            }
        )
    frame = pd.DataFrame(rows)
    normal = score_sector_samples(frame)
    mature_frame = frame.copy()
    mature_frame.loc[9, ["ret_60", "ret_120"]] = [0.8, 1.2]
    mature = score_sector_samples(mature_frame)

    assert normal.loc[9, "evidence_score"] == 100.0
    assert mature.loc[9, "evidence_score"] == 75.0


def test_recent_breadth_is_auxiliary_and_keeps_main_score() -> None:
    samples = pd.DataFrame(
        {
            "ts_code": ["BK0001.DC"],
            "trade_date": ["20260130"],
            "evidence_score": [72.0],
        }
    )
    dates = pd.bdate_range(end="2026-01-30", periods=60)
    breadth = pd.DataFrame(
        {
            "ts_code": ["BK0001.DC"] * len(dates),
            "trade_date": dates.strftime("%Y%m%d"),
            "up_num": np.arange(20, 80),
            "down_num": np.arange(80, 20, -1),
            "leading_pct": [5.0] * len(dates),
        }
    )
    result = merge_recent_breadth(samples, breadth)

    assert result.loc[0, "evidence_score"] == 72.0
    assert result.loc[0, "breadth_20"] > 0.5
    assert result.loc[0, "breadth_acceleration"] > 0
    assert result.loc[0, "leading_pct_20"] == 5.0


def test_state_audit_separates_quiet_confirming_and_overheated() -> None:
    frame = pd.DataFrame(
        {
            "ret_20": [0.03, 0.08, 0.20, -0.03],
            "ret_60": [0.00, 0.20, 0.60, 0.00],
            "ret_120": [0.05, 0.30, 0.80, 0.00],
            "amount_ratio_20_120": [1.20, 1.30, 1.40, 1.20],
            "turnover_ratio_20_120": [1.10, 1.20, 1.30, 1.10],
            "distance_to_high_120": [-0.15, -0.05, -0.02, -0.10],
            "breadth_20": [0.56, 0.60, 0.70, 0.60],
            "breadth_acceleration": [0.06, 0.08, 0.10, 0.08],
        }
    )
    result = classify_states(frame)

    assert result["state"].tolist() == [
        "quiet_accumulation",
        "confirming",
        "overheated",
        "no_signal",
    ]
    assert result["diffusion_confirmed"].tolist() == [True, True, True, True]


def test_current_theme_summary_uses_visible_subsets_for_widths() -> None:
    stocks = pd.DataFrame(
        {
            "theme_id": ["theme"] * 4,
            "theme_name": ["主题"] * 4,
            "board_code": ["BK0001.DC"] * 4,
            "market_visible": [True, True, True, False],
            "ret_20": [0.10, 0.05, -0.05, np.nan],
            "amount_ratio_20_120": [1.20, 1.10, 0.90, np.nan],
            "finance_visible": [True, True, False, False],
            "tr_yoy": [10.0, -5.0, np.nan, np.nan],
            "netprofit_yoy": [20.0, 5.0, np.nan, np.nan],
            "positive_forecast": [True, False, False, False],
            "margin_visible": [True, True, False, False],
            "margin_net_buy_20d": [10.0, -2.0, np.nan, np.nan],
        }
    )
    board_states = pd.DataFrame(
        {
            "board_code": ["BK0001.DC"],
            "state": ["quiet_accumulation"],
            "ret_20": [0.03],
            "ret_60": [0.08],
            "amount_ratio_20_120": [1.2],
            "breadth_20": [0.60],
            "breadth_acceleration": [0.06],
        }
    )

    result = summarize_themes(stocks, board_states).iloc[0]

    assert result["board_state"] == "quiet_accumulation"
    assert result["member_count"] == 4
    assert result["market_coverage"] == 0.75
    assert result["revenue_growth_positive_share"] == 0.5
    assert result["profit_growth_positive_share"] == 1.0
    assert result["margin_positive_share"] == 0.5


def test_case_summary_does_not_count_invisible_financial_rows() -> None:
    stocks = pd.DataFrame(
        {
            "case_id": ["case"] * 3,
            "theme": ["案例"] * 3,
            "signal_date": ["20240131"] * 3,
            "market_visible": [True, True, False],
            "ret_20": [0.10, -0.10, 2.0],
            "ret_60": [0.20, 0.05, 2.0],
            "amount_ratio_20_120": [1.20, 0.80, 3.0],
            "finance_visible": [True, False, False],
            "tr_yoy": [10.0, 100.0, 100.0],
            "netprofit_yoy": [-5.0, 100.0, 100.0],
            "positive_forecast": [True, False, False],
        }
    )
    board_events = pd.DataFrame(
        {
            "case_id": ["case"],
            "evidence_score": [42.0],
            "ret_60": [0.08],
            "amount_ratio_20_120": [1.1],
            "future_ret_60": [0.35],
            "future_excess_60": [0.22],
        }
    )

    result = summarize_cases(stocks, board_events).iloc[0]

    assert result["price_20_positive_share"] == 0.5
    assert result["revenue_growth_positive_share"] == 1.0
    assert result["profit_growth_positive_share"] == 0.0
    assert result["board_evidence_score"] == 42.0
