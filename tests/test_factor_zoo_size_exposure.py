"""因子动物园持仓市值归因测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples.factor_zoo_size_exposure_metrics import (
    compare_style_groups,
    evaluate_size_exposure_gate,
    summarize_size_exposure,
)
from examples import factor_zoo_size_exposure_study as study


STYLE_GROUPS = {
    "high_a": "HIGH_MIDCAP_CORRELATION",
    "high_b": "HIGH_MIDCAP_CORRELATION",
    "low_a": "LOW_MIDCAP_CORRELATION",
    "low_b": "LOW_MIDCAP_CORRELATION",
}


def test_size_exposure_confirms_smaller_high_correlation_holdings() -> None:
    """高相关代表实际更偏小市值时应通过持仓级门槛。"""
    holdings = pd.DataFrame(
        [
            *_records("high_a", [0.10, 0.20, 0.30, 0.40]),
            *_records("high_b", [0.15, 0.25, 0.35, 0.45]),
            *_records("low_a", [0.55, 0.65, 0.75, 0.85]),
            *_records("low_b", [0.60, 0.70, 0.80, 0.90]),
        ]
    )
    correlations = {
        "high_a": 0.95,
        "high_b": 0.90,
        "low_a": 0.30,
        "low_b": 0.40,
    }

    rows = summarize_size_exposure(
        holdings,
        correlations,
        STYLE_GROUPS,
    )
    comparison = compare_style_groups(rows)
    gate = evaluate_size_exposure_gate(comparison)

    assert comparison["low_minus_high_size_percentile"] > 0.30
    assert comparison["style_corr_vs_size_spearman"] < -0.50
    assert gate["passed"] is True


def test_size_exposure_rejects_incomplete_market_cap_coverage() -> None:
    """市值代理覆盖不足时不得确认持仓级结论。"""
    holdings = pd.DataFrame(
        [
            *_records("high_a", [0.10, None, 0.30, 0.40]),
            *_records("high_b", [0.15, 0.25, 0.35, 0.45]),
            *_records("low_a", [0.55, 0.65, 0.75, 0.85]),
            *_records("low_b", [0.60, 0.70, 0.80, 0.90]),
        ]
    )
    correlations = {
        "high_a": 0.95,
        "high_b": 0.90,
        "low_a": 0.30,
        "low_b": 0.40,
    }

    comparison = compare_style_groups(
        summarize_size_exposure(
            holdings,
            correlations,
            STYLE_GROUPS,
        )
    )
    gate = evaluate_size_exposure_gate(comparison)

    assert comparison["minimum_coverage"] == pytest.approx(0.75)
    assert gate["checks"]["all_strategy_coverage_at_least_90pct"] is False
    assert gate["passed"] is False


def test_study_reuses_same_source_and_file_versions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """源归因和输入文件未变时不得重新构造历史持仓。"""
    monkeypatch.setattr(
        study,
        "_load_source_result",
        lambda paths: {
            "run_fingerprint": "source-fingerprint",
            "metrics": {},
        },
    )
    monkeypatch.setattr(study, "_source_file_versions", lambda paths: [])

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
        lambda *args, **kwargs: pytest.fail("不应重建历史持仓"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _records(
    strategy_id: str,
    percentiles: list[float | None],
) -> list[dict[str, object]]:
    """构造两期等权持仓市值分位。"""
    rows: list[dict[str, object]] = []
    for index, percentile in enumerate(percentiles):
        rows.append(
            {
                "strategy_id": strategy_id,
                "signal_date": "20200131" if index < 2 else "20200228",
                "symbol": f"{strategy_id}_{index}",
                "market_cap_proxy": (
                    None if percentile is None else percentile * 1_000_000
                ),
                "market_cap_percentile": percentile,
            }
        )
    return rows
