"""多策略收益源地图指标测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from examples.strategy_alpha_source_map_metrics import (
    build_correlation_clusters,
    effective_bet_count,
    residual_correlation_matrix,
)


def test_effective_bets_equals_count_for_identity_matrix() -> None:
    """完全独立的三个收益源应得到三个有效押注。"""
    matrix = {
        "A": {"A": 1.0, "B": 0.0, "C": 0.0},
        "B": {"A": 0.0, "B": 1.0, "C": 0.0},
        "C": {"A": 0.0, "B": 0.0, "C": 1.0},
    }

    assert effective_bet_count(matrix) == pytest.approx(3.0)


def test_residual_correlation_removes_shared_market_beta() -> None:
    """只共享市场Beta的两个策略在残差层应接近不相关。"""
    benchmark = pd.Series(
        [0.01, -0.02, 0.015, -0.005, 0.008, -0.012] * 20
    )
    noise_a = pd.Series([0.001, -0.001] * 60)
    noise_b = pd.Series([0.001, 0.001, -0.001, -0.001] * 30)
    frame = pd.DataFrame(
        {
            "benchmark": benchmark,
            "A": 0.6 * benchmark + noise_a,
            "B": 0.7 * benchmark + noise_b,
        }
    )

    matrix = residual_correlation_matrix(frame, ["A", "B"])

    assert abs(matrix["A"]["B"]) < 0.05


def test_clusters_use_transitive_correlation_links() -> None:
    """A-B与B-C同源时应通过连通关系归为一个簇。"""
    matrix = {
        "A": {"A": 1.0, "B": 0.8, "C": 0.2},
        "B": {"A": 0.8, "B": 1.0, "C": 0.8},
        "C": {"A": 0.2, "B": 0.8, "C": 1.0},
    }

    assert build_correlation_clusters(matrix) == [["A", "B", "C"]]
