"""Quality Overlay 稳健性研究入口测试。"""

import pandas as pd
import pytest

from examples.quality_overlay_robustness_study import (
    EXPOSURES,
    THRESHOLDS,
    WINDOWS,
    build_heatmap_matrix,
    effective_end_date,
    heatmap_title,
    parameter_combinations,
    summarize_year_stability,
)


def test_parameter_grid_contains_all_120_unique_combinations() -> None:
    combinations = parameter_combinations()

    assert len(combinations) == 120
    assert len(set(combinations)) == 120
    assert {item[0] for item in combinations} == set(WINDOWS)
    assert {item[1] for item in combinations} == set(THRESHOLDS)
    assert {item[2] for item in combinations} == set(EXPOSURES)


def test_heatmap_matrix_keeps_selected_exposure_dimension() -> None:
    frame = pd.DataFrame(
        [
            {"窗口": 10, "阈值": 0.35, "低波动仓位": 0.2, "夏普比率": 0.7},
            {"窗口": 10, "阈值": 0.40, "低波动仓位": 0.2, "夏普比率": 0.8},
            {"窗口": 10, "阈值": 0.35, "低波动仓位": 0.3, "夏普比率": 9.9},
        ]
    )

    matrix = build_heatmap_matrix(frame, "夏普比率", exposure=0.2)

    assert matrix.loc[10, 0.35] == 0.7
    assert matrix.loc[10, 0.40] == 0.8
    assert 9.9 not in matrix.to_numpy()


def test_heatmap_title_uses_ascii_for_default_pillow_font() -> None:
    """默认字体不含中文，图片标题必须保持可读。"""
    assert heatmap_title("夏普比率") == "Sharpe"
    assert heatmap_title("Calmar") == "Calmar"


def test_summarize_year_stability_measures_concentration_without_2015() -> None:
    annual = pd.DataFrame({"年份": [2015, 2016, 2017], "收益": [1.0, 0.10, -0.05], "超额收益": [0.8, 0.02, -0.01]})

    summary = summarize_year_stability(annual)

    assert summary["正收益年份"] == 2
    assert summary["正超额年份"] == 2
    assert summary["剔除2015后年化"] == pytest.approx((1.10 * 0.95) ** 0.5 - 1)


def test_effective_end_date_does_not_claim_future_data() -> None:
    assert effective_end_date("2026-12-31", pd.Timestamp("2026-06-15")) == "2026-06-15"
