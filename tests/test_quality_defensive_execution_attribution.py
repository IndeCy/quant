"""Quality防守袖套Paper执行压力归因测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples import (
    quality_defensive_assets_execution_attribution_study as study,
)


def test_scenarios_change_one_execution_dimension_at_a_time() -> None:
    """单因素场景必须保持另外两个执行参数不变。"""
    baseline = study.SCENARIOS["baseline"]

    assert study.SCENARIOS["delay_only"] == {
        **baseline,
        "execution_delay": 2,
    }
    assert study.SCENARIOS["liquidity_only"] == {
        **baseline,
        "participation": 0.002,
    }
    assert study.SCENARIOS["slippage_only"] == {
        **baseline,
        "slippage_bps": 20.0,
    }


def test_attribution_uses_frozen_largest_impact_rules() -> None:
    """持仓与收益主导因素必须分别按声明规则计算。"""
    metrics = {
        "baseline": {"annualized_return": 0.12},
        "delay_only": {"annualized_return": 0.09},
        "liquidity_only": {"annualized_return": 0.11},
        "slippage_only": {"annualized_return": 0.115},
    }
    diagnostics = {
        "delay_only": {"average_actual_position_gap": 0.08},
        "liquidity_only": {"average_actual_position_gap": 0.15},
        "slippage_only": {"average_actual_position_gap": 0.02},
    }

    result = study.identify_dominant_driver(metrics, diagnostics)

    assert result["position_gap_driver_id"] == "liquidity_only"
    assert result["return_loss_driver_id"] == "delay_only"


def test_execution_attribution_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同正交场景不得重复执行历史撮合。"""

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study.STRATEGY_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复撮合"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True
