"""长期反转正式研究的冻结语义测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from examples import long_term_reversal_study as study


def test_research_spec_uses_explicit_grid_risk_mode() -> None:
    """风险层必须明确执行20日、45%、30%的 GRID 语义。"""
    risk = study.RESEARCH_SPEC.definition["risk_overlay"]

    assert risk == {
        "mode": "GRID",
        "window": 20,
        "threshold": 0.45,
        "reduced_exposure": 0.30,
    }


def test_targets_select_lowest_long_term_returns() -> None:
    """Top40 必须来自历史收益最低的股票，不得反向。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 45,
            "symbol": [f"S{i:03d}" for i in range(45)],
            "name": [f"股票{i}" for i in range(45)],
            "long_term_return": [float(i) for i in range(45)],
            "ret120": [0.0] * 45,
            "vol60": [0.02] * 45,
            "adv_rmb": [50_000_000.0] * 45,
        }
    )

    _, holdings, counts = study.build_targets(frame)

    assert len(holdings) == 40
    assert set(holdings["symbol"]) == {f"S{i:03d}" for i in range(40)}
    assert counts["min"] == 45.0


def test_gate_rejects_excessive_drawdown() -> None:
    """即使收益达标，任一折回撤超过30%仍必须拒绝。"""
    good = {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.05,
        "annual_turnover": 5.0,
    }
    metrics = {key: dict(good) for key in [*study.FOLDS, "full"]}
    metrics["2018_2020"]["max_drawdown"] = -0.31

    gate = study.evaluate_gate(metrics, quality_correlation=0.4)

    assert gate["passed"] is False
    assert gate["checks"]["worst_fold_drawdown_within_30pct"] is False


def test_feasibility_dependency_rejects_failed_latest_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """正式回测不能从Markdown或旧通过记录推断门禁状态。"""
    class Repository:
        def __init__(self, path) -> None:
            self.path = path

        def load_experiment_detail(self, experiment_id: str):
            return {
                "latest_run": {
                    "status": "SUCCESS",
                    "outcome": "REJECTED",
                }
            }

    monkeypatch.setattr(study, "SystemRepository", Repository)

    with pytest.raises(RuntimeError, match="门禁未通过"):
        study._require_feasibility_passed(study.RuntimePaths(tmp_path))
