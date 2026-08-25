"""Quality Balanced Value 低效窗口归因测试。"""

from __future__ import annotations

import pandas as pd
from pandas.testing import assert_series_equal
import pytest

from examples.quality_balanced_value_window_attribution_metrics import (
    ATTRIBUTION_VARIANTS,
    build_leave_one_out_summary,
    diagnose_drag,
    score_factor_leg_subset,
)
from factors.quality_market_extension import score_quality_market_extension


def _factor_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [f"{index:06d}.SZ" for index in range(1, 11)],
            "roe": [5, 8, 9, 11, 13, 15, 17, 18, 20, 22],
            "roa": [2, 3, 4, 5, 6, 7, 8, 9, 10, 12],
            "ocf_to_or": [0.05, 0.08, 0.09, 0.10, 0.12, 0.15, 0.18, 0.20, 0.24, 0.30],
            "earnings_yield": [0.12, 0.10, 0.09, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02],
            "book_yield": [0.08, 0.07, 0.09, 0.06, 0.10, 0.05, 0.11, 0.04, 0.12, 0.03],
        }
    )


def test_balanced_scoring_matches_production_formula() -> None:
    """三腿完整组合必须与生产策略评分公式逐股一致。"""
    frame = _factor_frame()
    actual = score_factor_leg_subset(
        frame,
        ATTRIBUTION_VARIANTS["balanced"],
    ).set_index("symbol")["factor_score"].sort_index()
    expected = score_quality_market_extension(
        frame,
        {"earnings_yield": 0.10, "book_yield": 0.10},
    ).set_index("symbol")["factor_score"].sort_index()

    assert_series_equal(actual, expected)


def test_single_factor_leg_preserves_expected_direction() -> None:
    """纯E/P组合应优先选择收益率更高的股票。"""
    scored = score_factor_leg_subset(
        _factor_frame(),
        ATTRIBUTION_VARIANTS["earnings_yield_only"],
    )

    assert scored.iloc[0]["symbol"] == "000001.SZ"
    assert scored.iloc[-1]["symbol"] == "000010.SZ"


def test_leave_one_out_summary_uses_balanced_as_fixed_control() -> None:
    """边际贡献必须由原策略减去对应删除腿组合。"""
    metrics = {
        variant: {
            "window": {
                "annualized_return": 0.10,
                "max_drawdown": -0.20,
                "sharpe": 0.40,
                "calmar": 0.50,
                "excess_return": 0.02,
            }
        }
        for variant in ATTRIBUTION_VARIANTS
    }
    metrics["balanced"]["window"]["sharpe"] = 0.55
    metrics["quality_only"]["window"]["sharpe"] = 0.45

    summary = build_leave_one_out_summary(metrics, ["window"])

    assert summary["by_window"]["window"][
        "combined_value_on_quality"
    ]["sharpe"] == pytest.approx(0.10)


def test_diagnosis_detects_common_weak_factor_regime() -> None:
    """三个独立因子腿都弱时不得误判为某一个扩展因子拖累。"""
    metrics = {
        variant: {
            "window": {
                "annualized_return": 0.05,
                "max_drawdown": -0.20,
                "sharpe": 0.20,
                "calmar": 0.25,
                "excess_return": 0.01,
            }
        }
        for variant in ATTRIBUTION_VARIANTS
    }
    summary = build_leave_one_out_summary(metrics, ["window"])

    diagnosis = diagnose_drag(metrics, ["window"], summary)

    assert diagnosis["label"] == "COMMON_FACTOR_REGIME"
