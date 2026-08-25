"""跨资产双动量固定风险层研究测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples import cross_asset_dual_momentum_risk_study as study


def test_overlay_gate_requires_material_drawdown_improvement() -> None:
    """风险层即使自身合格，也必须相对原策略显著改善回撤。"""
    good = _metrics(-0.20)
    metrics = {key: good for key in [*study.base.FOLDS, "full"]}
    base_metrics = {"full": _metrics(-0.30)}

    gate = study.evaluate_gate(metrics, 0.30, base_metrics)

    assert gate["passed"] is False
    assert gate["full_drawdown_improvement"] == pytest.approx(0.10)
    assert gate["checks"]["full_drawdown_improves_base_by_15pct"] is False


def test_overlay_gate_passes_only_when_all_fixed_checks_pass() -> None:
    """低相关、低回撤和跨折稳定必须同时成立。"""
    good = _metrics(-0.20)
    metrics = {key: good for key in [*study.base.FOLDS, "full"]}
    base_metrics = {"full": _metrics(-0.50)}

    gate = study.evaluate_gate(metrics, 0.30, base_metrics)

    assert gate["passed"] is True
    assert gate["full_drawdown_improvement"] == pytest.approx(0.30)


def test_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """同一基线和风险层定义命中指纹时不能重跑。"""

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
        lambda *args, **kwargs: pytest.fail("不应重复计算"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _metrics(drawdown: float) -> dict[str, float]:
    return {
        "annualized_return": 0.08,
        "max_drawdown": drawdown,
        "sharpe": 0.70,
        "calmar": 0.40,
        "excess_return": 0.10,
        "annual_turnover": 2.0,
        "trade_count": 20.0,
        "execution_cost_impact": 0.01,
    }
