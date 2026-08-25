"""因子动物园共同模式归因测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples.factor_zoo_common_mode_metrics import (
    build_annual_metric_matrix,
    build_style_attribution,
    evaluate_common_mode_gate,
    summarize_correlation,
)
from examples import factor_zoo_common_mode_study as study


def test_common_mode_metrics_detect_redundant_factors() -> None:
    """多个同方向年度收益序列应表现为高共同成分和低有效广度。"""
    matrix = pd.DataFrame(
        {
            "a": [0.10, -0.05, 0.20, -0.10, 0.15],
            "b": [0.11, -0.04, 0.18, -0.09, 0.14],
            "c": [0.09, -0.06, 0.22, -0.11, 0.16],
            "d": [0.12, -0.03, 0.19, -0.08, 0.13],
            "e": [0.08, -0.07, 0.21, -0.12, 0.17],
        },
        index=range(2020, 2025),
    )

    summary = summarize_correlation(matrix)

    assert summary["first_component_variance_share"] > 0.95
    assert summary["effective_breadth"] < 1.10


def test_style_attribution_removes_shared_midcap_exposure() -> None:
    """剔除中盘价差后，因子间相关和有效押注数应改善。"""
    years = list(range(2015, 2023))
    midcap = pd.Series(
        [0.30, -0.10, 0.15, -0.20, 0.25, -0.12, 0.18, -0.08],
        index=years,
    )
    matrix = pd.DataFrame(
        {
            f"factor_{index}": midcap * (1.0 + index * 0.1)
            + pd.Series(
                [0.01 * ((year + index) % 3 - 1) for year in years],
                index=years,
            )
            for index in range(5)
        }
    )
    spreads = pd.DataFrame(
        {
            "csi500_minus_hs300": midcap,
            "chinext_minus_hs300": midcap * 0.4,
        }
    )

    attribution = build_style_attribution(matrix, spreads)

    assert attribution["csi500_spread_regression"]["r_squared"] > 0.95
    assert attribution["leave_one_year_out_min_r_squared"] > 0.90
    assert attribution["strategy_correlation_ge_070_share"] == 1.0
    assert (
        attribution["residual_correlation_summary"]["effective_breadth"]
        > summarize_correlation(matrix)["effective_breadth"]
    )


def test_complete_panel_excludes_missing_factor_year() -> None:
    """缺少固定年份的实验不能混入主相关矩阵。"""
    years = list(range(2020, 2025))
    runs = [
        _run("complete", _annual_values(years, 0.10)),
        _run("missing", {2020: 0.1}),
        _run("c", _annual_values(years, 0.20)),
        _run("d", _annual_values(years, 0.30)),
        _run("e", _annual_values(years, -0.10)),
        _run("f", _annual_values(years, 0.00)),
    ]

    matrix, excluded = build_annual_metric_matrix(
        runs,
        metric_name="excess_return",
        years=years,
    )

    assert list(matrix.columns) == ["c", "complete", "d", "e", "f"]
    assert excluded == ["missing"]


def test_common_mode_gate_requires_all_frozen_checks() -> None:
    """共同模式结论必须同时满足成分、风格解释和广度门槛。"""
    gate = evaluate_common_mode_gate(
        {
            "first_component_variance_share": 0.80,
            "effective_breadth": 1.50,
        },
        {
            "csi500_spread_regression": {"r_squared": 0.86},
            "leave_one_year_out_min_r_squared": 0.71,
            "strategy_correlation_ge_070_share": 0.85,
        },
    )

    assert gate["passed"] is True


def test_study_reuses_identical_source_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """源实验和ETF版本不变时不得重复执行元研究。"""
    monkeypatch.setattr(study, "load_source_manifest", lambda paths: [])
    monkeypatch.setattr(study, "_style_file_versions", lambda paths: [])

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复执行共同模式审计"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _run(
    experiment_id: str,
    annual_values: dict[int, float],
) -> dict[str, object]:
    """构造年度指标实验。"""
    return {
        "experiment_id": experiment_id,
        "metrics": {
            "annual_metrics": {
                str(year): {"excess_return": value}
                for year, value in annual_values.items()
            }
        },
    }


def _annual_values(years: list[int], start: float) -> dict[int, float]:
    """生成具备年度变化的完整测试面板。"""
    return {
        year: start + index * 0.01
        for index, year in enumerate(years)
    }
