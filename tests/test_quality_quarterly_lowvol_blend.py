"""Quality核心与季度低波卫星组合研究测试。"""

from __future__ import annotations

import math

import examples.quality_quarterly_lowvol_blend_study as study
from examples.quality_quarterly_lowvol_blend_study import blend_sleeve_targets
from runtime.paths import RuntimePaths


def test_blend_sleeve_targets_carries_quarterly_selection() -> None:
    """季度卫星持仓应跨月保持，核心仍按月更新。"""
    core = {
        "20260130": {"CORE_A": 1.0},
        "20260227": {"CORE_B": 1.0},
        "20260331": {"CORE_C": 1.0},
        "20260430": {"CORE_D": 1.0},
    }
    satellite = {
        "20260331": {"SAT_A": 0.5, "SAT_B": 0.5},
    }

    result = blend_sleeve_targets(core, satellite)

    assert result["20260130"] == {"CORE_A": 1.0}
    assert result["20260227"] == {"CORE_B": 1.0}
    assert math.isclose(result["20260331"]["CORE_C"], 0.70)
    assert math.isclose(result["20260331"]["SAT_A"], 0.15)
    assert math.isclose(result["20260430"]["CORE_D"], 0.70)
    assert math.isclose(result["20260430"]["SAT_B"], 0.15)


def test_blend_adds_weights_for_overlapping_symbol() -> None:
    """同一股票被两个袖套选中时应累加权重，而不是重复持仓。"""
    result = blend_sleeve_targets(
        {"20260331": {"SAME": 0.5, "CORE": 0.5}},
        {"20260331": {"SAME": 0.25, "SAT": 0.75}},
    )

    assert math.isclose(result["20260331"]["SAME"], 0.425)
    assert math.isclose(sum(result["20260331"].values()), 1.0)


def test_reused_blend_study_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    """相同组合指纹必须在加载两套信号前复用。"""
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-blend-run"}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("must not calculate")),
    )

    result = study.run_study(RuntimePaths(tmp_path), "20260723")

    assert result["reused"] is True
    assert result["run_fingerprint"] == "same-blend-run"
