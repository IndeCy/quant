"""因子动物园走步风格残差测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples.factor_zoo_walk_forward_residual_metrics import (
    LOCKED_TRAIN_YEARS,
    estimate_style_beta,
    evaluate_single_candidate,
)
from examples import factor_zoo_walk_forward_residual_study as study


def test_locked_beta_does_not_read_locked_years() -> None:
    """修改锁定期收益不得改变2015至2021训练出的Beta。"""
    years = list(range(2015, 2027))
    style = pd.Series(
        [0.10, -0.05, 0.08, -0.03, 0.12, -0.04,
         0.06, -0.02, 0.07, -0.01, 0.05, -0.06],
        index=years,
    )
    excess = style * 1.5 + 0.03
    changed = excess.copy()
    changed.loc[2022:2026] = [2.0, -2.0, 3.0, -3.0, 4.0]

    original_beta = estimate_style_beta(
        excess,
        style,
        LOCKED_TRAIN_YEARS,
    )
    changed_beta = estimate_style_beta(
        changed,
        style,
        LOCKED_TRAIN_YEARS,
    )

    assert original_beta == pytest.approx(1.5)
    assert changed_beta == pytest.approx(original_beta)


def test_independent_positive_residual_passes_gate() -> None:
    """跨窗口稳定正残差且尾部受控时应通过全部门槛。"""
    years = list(range(2015, 2027))
    style = pd.Series(
        [0.10, -0.05, 0.08, -0.03, 0.12, -0.04,
         0.06, -0.02, 0.07, -0.01, 0.05, -0.06],
        index=years,
    )
    residual = pd.Series(
        [0.03, 0.04, 0.02, 0.05, 0.02, 0.04,
         0.03, 0.02, 0.04, -0.01, 0.03, 0.02],
        index=years,
    )

    result = evaluate_single_candidate(
        "stable",
        style * 1.2 + residual,
        style,
    )

    assert result["gate_passed"] is True
    assert result["locked_positive_year_share"] >= 0.60


def test_positive_means_still_fail_when_residual_is_unstable() -> None:
    """均值为正但极端亏损和信息比率不足时不能入选。"""
    years = list(range(2015, 2027))
    style = pd.Series(0.0, index=years)
    excess = pd.Series(
        [0.01, 0.02, 0.01, 0.02, 0.01, 0.02,
         0.01, 0.30, -0.25, 0.01, 0.01, 0.01],
        index=years,
    )

    result = evaluate_single_candidate("unstable", excess, style)

    assert result["locked_mean_residual"] > 0
    assert result["gate_passed"] is False
    assert "locked_worst_residual_within_20pct" in result["failed_checks"]


def test_study_reuses_same_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """实验和ETF版本不变时不得重复执行残差审计。"""
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
        lambda *args, **kwargs: pytest.fail("不应重复执行残差审计"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True
