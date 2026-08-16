"""跨资产双动量分级恢复研究测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples import cross_asset_dual_momentum_stateful_risk_study as study


def test_gate_rejects_state_machine_when_turnover_remains_high() -> None:
    """状态机若仍违反原换手门槛，不能因回撤改善而晋级。"""
    good = _metrics(-0.20)
    metrics = {key: dict(good) for key in [*study.base.FOLDS, "full"]}
    metrics["full"]["annual_turnover"] = 5.0
    base_metrics = {"full": _metrics(-0.50)}
    binary_metrics = {"full": _metrics(-0.30)}

    gate = study.evaluate_gate(metrics, 0.30, base_metrics, binary_metrics)

    assert gate["passed"] is False
    assert gate["checks"]["annual_turnover_below_4x"] is False


def test_gate_requires_execution_cost_not_worse_than_binary() -> None:
    """渐进恢复不能以显著更高执行成本换取表面回撤改善。"""
    good = _metrics(-0.20)
    metrics = {key: dict(good) for key in [*study.base.FOLDS, "full"]}
    metrics["full"]["execution_cost_impact"] = 0.12
    base_metrics = {"full": _metrics(-0.50)}
    binary_metrics = {"full": {**_metrics(-0.30), "execution_cost_impact": 0.10}}

    gate = study.evaluate_gate(metrics, 0.30, base_metrics, binary_metrics)

    assert gate["passed"] is False
    assert gate["checks"]["execution_cost_not_worse_binary_10pct"] is False


def test_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同状态机和数据版本不得重复回测。"""
    monkeypatch.setattr(study, "_data_version", lambda paths: "stable")

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
        "execution_cost_impact": 0.10,
    }
