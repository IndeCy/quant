"""T+1开盘重算历史Paper研究测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples import quality_defensive_assets_open_aware_paper_study as study


def test_open_aware_gate_requires_low_execution_drift() -> None:
    """收益合格也不能掩盖成交后持仓漂移超限。"""
    m0 = {
        "annualized_return": 0.12,
        "max_drawdown": -0.18,
        "sharpe": 0.80,
    }
    paper = {
        "annualized_return": 0.115,
        "max_drawdown": -0.19,
        "sharpe": 0.76,
    }
    diagnostics = {
        "tracking_error": 0.01,
        "successful_order_ratio_vs_m0": 0.99,
        "incremental_rejection_rate_vs_m0": 0.01,
        "average_post_execution_drift": 0.04,
        "latest_position_drift": 0.03,
    }

    passed = study.evaluate_open_aware_gate(m0, paper, diagnostics)
    diagnostics["average_post_execution_drift"] = 0.06
    failed = study.evaluate_open_aware_gate(m0, paper, diagnostics)

    assert passed["passed"] is True
    assert failed["passed"] is False
    assert (
        failed["checks"]["average_post_execution_drift_below_5pct"]
        is False
    )


def test_open_aware_study_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """完全相同的历史执行研究不得重复消耗算力。"""

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
        lambda *args, **kwargs: pytest.fail("不应重复历史回放"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260723")

    assert result["reused"] is True
