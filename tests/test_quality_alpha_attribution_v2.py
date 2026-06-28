"""Quality Alpha V2 归因研究辅助函数测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from examples.quality_alpha_attribution_v2 import (
    average_holding_overlap,
    build_factor_correlation,
    build_marginal_contribution,
    score_factor_frame,
)


def test_score_factor_frame_supports_single_and_pair_factors() -> None:
    """单因子和双因子必须复用同一缩尾与标准化评分路径。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "roe": [10.0, 20.0, 30.0],
            "roa": [3.0, 2.0, 1.0],
            "ocf_to_or": [1.0, 1.0, 1.0],
        }
    )

    roe_only = score_factor_frame(frame, ["roe"])
    roe_roa = score_factor_frame(frame, ["roe", "roa"])

    assert roe_only.iloc[0]["symbol"] == "C"
    assert set(roe_roa.columns) >= {"factor_score", "roe_z", "roa_z"}


def test_average_holding_overlap_uses_jaccard_by_signal_date() -> None:
    left = {"20240131": ["A", "B"], "20240229": ["A", "C"]}
    right = {"20240131": ["A", "C"], "20240229": ["A", "C"]}

    assert average_holding_overlap(left, right) == pytest.approx((1 / 3 + 1.0) / 2)


def test_build_factor_correlation_outputs_pearson_and_spearman() -> None:
    frame = pd.DataFrame({"roe": [1, 2, 3], "roa": [1, 2, 4], "ocf_to_or": [3, 2, 1]})

    result = build_factor_correlation(frame, ["roe", "roa", "ocf_to_or"])

    assert set(result) == {"pearson", "spearman"}
    assert result["pearson"].loc["roe", "roe"] == pytest.approx(1.0)
    assert result["spearman"].loc["roe", "ocf_to_or"] == pytest.approx(-1.0)


def test_build_marginal_contribution_compares_quality_to_removed_factor_versions() -> None:
    metrics = pd.DataFrame(
        [
            {"策略": "Quality V1", "夏普": 1.0, "Calmar": 0.5, "最大回撤": -0.3, "超额收益": 2.0},
            {"策略": "ROA + OCF_TO_OR", "夏普": 0.8, "Calmar": 0.4, "最大回撤": -0.4, "超额收益": 1.5},
        ]
    )

    result = build_marginal_contribution(metrics, {"删除ROE": "ROA + OCF_TO_OR"})

    row = result.iloc[0]
    assert row["退化策略"] == "ROA + OCF_TO_OR"
    assert row["Sharpe变化"] == pytest.approx(-0.2)
    assert row["最大回撤变化"] == pytest.approx(-0.1)
