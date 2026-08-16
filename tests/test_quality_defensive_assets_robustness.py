"""Quality防守袖套鲁棒性确认测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import quality_defensive_assets_robustness_study as study
from examples.quality_defensive_assets_metrics import evaluate_robustness_gate


def test_shift_exposure_adds_exactly_one_trading_day_delay() -> None:
    """风险信号压力场景只能延迟，不得预读未来状态。"""
    exposure = pd.Series(
        [1.0, 0.3, 0.3, 1.0],
        index=pd.bdate_range("2024-01-02", periods=4),
    )

    shifted = study.shift_exposure_one_trading_day(exposure)

    assert shifted.tolist() == [1.0, 1.0, 0.3, 0.3]


def test_robustness_gate_passes_only_when_all_scenarios_survive() -> None:
    """鲁棒性门槛不能通过挑选表现最好的场景规避失败。"""
    metrics = _scenario_metrics()
    annual = {
        study.BASELINE_ID: {
            str(year): _metrics(0.08, -0.10, 0.80)
            for year in range(2015, 2027)
        }
    }

    passed = evaluate_robustness_gate(
        metrics,
        annual,
        baseline_id=study.BASELINE_ID,
        neighborhood_ids=study.NEIGHBORHOOD_IDS,
        cost_stress_ids=study.COST_STRESS_IDS,
        delay_id=study.DELAY_ID,
        single_asset_ids=study.SINGLE_ASSET_IDS,
    )
    metrics["slippage_20bps"]["full"]["annualized_return"] = 0.08
    failed = evaluate_robustness_gate(
        metrics,
        annual,
        baseline_id=study.BASELINE_ID,
        neighborhood_ids=study.NEIGHBORHOOD_IDS,
        cost_stress_ids=study.COST_STRESS_IDS,
        delay_id=study.DELAY_ID,
        single_asset_ids=study.SINGLE_ASSET_IDS,
    )

    assert passed["passed"] is True
    assert failed["passed"] is False
    assert failed["checks"]["execution_cost_stress_survives"] is False


def test_robustness_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """同一组冻结压力场景不得重复执行耗时回测。"""

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


def _scenario_metrics() -> dict[str, dict[str, dict[str, float]]]:
    """构造全部场景及主方案四个分段。"""
    scenario_ids = (
        study.BASELINE_ID,
        *study.NEIGHBORHOOD_IDS,
        *study.COST_STRESS_IDS,
        study.DELAY_ID,
        *study.SINGLE_ASSET_IDS,
    )
    metrics = {
        scenario_id: {"full": _metrics(0.11, -0.20, 0.75)}
        for scenario_id in scenario_ids
    }
    metrics[study.BASELINE_ID].update(
        {
            fold: _metrics(0.08, -0.18, 0.70)
            for fold in study.base_study.FOLDS
        }
    )
    return metrics


def _metrics(
    annual_return: float,
    drawdown: float,
    sharpe: float,
) -> dict[str, float]:
    return {
        "annualized_return": annual_return,
        "max_drawdown": drawdown,
        "sharpe": sharpe,
        "calmar": 0.60,
        "excess_return": 0.20,
        "annual_turnover": 5.0,
        "trade_count": 100.0,
        "execution_cost_impact": 0.02,
    }
