"""独立因子多折复验测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import factor_multifold_revalidation as study


def test_gate_rejects_candidate_with_one_deep_drawdown_fold() -> None:
    """其余指标合格时，任一折回撤超限仍不得通过。"""
    good = _metrics()
    metrics = {
        "2015_2017": good,
        "2018_2020": {**good, "max_drawdown": -0.40},
        "2021_2023": good,
        "2024_latest": good,
        "full": good,
    }

    result = study.evaluate_gate(metrics)

    assert result["passed"] is False
    assert result["checks"]["worst_fold_drawdown_within_30pct"] is False


def test_gate_requires_three_positive_folds() -> None:
    """全样本好看不能掩盖大多数阶段亏损。"""
    good = _metrics()
    losing = {**good, "annualized_return": -0.01, "sharpe": -0.1}
    metrics = {
        "2015_2017": losing,
        "2018_2020": losing,
        "2021_2023": good,
        "2024_latest": good,
        "full": good,
    }

    result = study.evaluate_gate(metrics)

    assert result["passed"] is False
    assert result["positive_folds"] == 2
    assert result["checks"]["at_least_three_positive_folds"] is False


def test_return_correlations_are_calculated_by_fold() -> None:
    """相关性必须使用各折内部日收益，不能用累计净值相关性。"""
    dates = pd.bdate_range("2024-01-02", periods=8)
    left, right = study.FROZEN_CANDIDATES
    nav = pd.DataFrame(
        {
            "trade_date": dates,
            left: [1.0, 1.1, 1.0, 1.2, 1.1, 1.3, 1.2, 1.4],
            right: [1.0, 1.2, 1.1, 1.3, 1.2, 1.4, 1.3, 1.5],
            "benchmark_510300": [1.0] * 8,
        }
    )

    result = study.build_return_correlations(
        nav,
        {"full": ("20240101", "20241231")},
    )

    expected = nav[[left, right]].pct_change().corr().loc[left, right]
    assert result["full"] == pytest.approx(expected)


def test_revalidation_reuses_identical_research_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同数据和定义必须复用，不能再次加载大表。"""

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "decision": "REJECT_ALL_CANDIDATES"}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新执行多折回测"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _metrics() -> dict[str, float]:
    """构造一组通过全部门槛的指标。"""
    return {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.10,
        "annual_turnover": 6.0,
        "trade_count": 20.0,
        "execution_cost_impact": 0.01,
    }
