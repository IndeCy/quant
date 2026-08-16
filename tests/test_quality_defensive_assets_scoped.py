"""Quality核心袖套风险预算研究测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import quality_defensive_assets_scoped_study as study
from examples.quality_defensive_assets_metrics import evaluate_scoped_gate
from portfolio.fixed_sleeve import build_core_scoped_sleeve_targets


def test_core_scoped_targets_keep_defensive_budget_fixed() -> None:
    """核心降至30%时，防守袖套不应被同步缩放。"""
    exposure = pd.Series(
        [1.0, 0.3, 0.3],
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-31"]),
    )
    targets = build_core_scoped_sleeve_targets(
        {
            "20240102": {"A": 1.0},
            "20240131": {"B": 1.0},
        },
        exposure,
        core_allocation=0.70,
        defensive_weights={"GOLD": 0.15, "BOND": 0.15},
    )

    assert targets["20240102"] == {"A": 0.70, "GOLD": 0.15, "BOND": 0.15}
    assert targets["20240103"] == {"A": 0.21, "GOLD": 0.15, "BOND": 0.15}
    assert targets["20240131"] == {"B": 0.21, "GOLD": 0.15, "BOND": 0.15}
    assert sum(targets["20240103"].values()) == pytest.approx(0.51)


def test_exposure_frame_maps_core_reduction_to_51_percent_total() -> None:
    """核心风险状态必须能追溯到组合有效总仓位。"""
    exposure = pd.Series(
        [1.0, 0.3],
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )

    frame = study.build_exposure_frame(exposure)

    assert frame["effective_total_exposure"].tolist() == pytest.approx([1.0, 0.51])


def test_scoped_gate_requires_both_absolute_and_relative_improvement() -> None:
    """通过门槛必须同时优于纯核心和整组合覆盖层。"""
    scoped = {
        key: _metrics(drawdown=-0.20, annual_return=0.12)
        for key in [*study.base_study.FOLDS, "full"]
    }
    core = {"full": _metrics(drawdown=-0.25, annual_return=0.13)}
    whole = {"full": _metrics(drawdown=-0.35, annual_return=0.10)}
    annual = {
        str(year): _metrics(drawdown=-0.10, annual_return=0.08)
        for year in range(2015, 2027)
    }

    gate = evaluate_scoped_gate(scoped, core, whole, annual)

    assert gate["passed"] is True
    assert gate["checks"]["drawdown_improves_core_by_3pct"] is True
    assert gate["checks"]["drawdown_improves_whole_overlay_by_5pct"] is True


def test_scoped_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同语义与数据版本不得重复扫描财务大表。"""

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
        lambda *args, **kwargs: pytest.fail("不应重复回测"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _metrics(
    *,
    drawdown: float,
    annual_return: float,
) -> dict[str, float]:
    """构造满足其余冻结门槛的最小指标。"""
    return {
        "annualized_return": annual_return,
        "max_drawdown": drawdown,
        "sharpe": 0.80,
        "calmar": 0.60,
        "excess_return": 0.20,
        "annual_turnover": 5.0,
        "trade_count": 100.0,
        "execution_cost_impact": 0.02,
    }
