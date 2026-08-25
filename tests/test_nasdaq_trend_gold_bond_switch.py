"""纳指趋势驱动黄金国债切换研究测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from examples import nasdaq_trend_gold_bond_switch_study as study
from runtime.paths import RuntimePaths


def test_definition_freezes_signal_weights_and_opportunity_cost() -> None:
    """研究必须在读取结果前冻结窗口、权重和直接标普机会成本。"""
    definition = study.RESEARCH_SPEC.definition

    assert definition["signal"]["formula"] == "nasdaq_ma20_gt_ma200"
    assert definition["portfolio"]["trend_active"] == {
        "159941.SZ": 0.60,
        "518880.SH": 0.40,
    }
    assert definition["portfolio"]["trend_inactive"] == {
        "518880.SH": 0.50,
        "511010.SH": 0.50,
    }
    assert definition["assets"]["hard_opportunity_cost"] == "513500.SH"
    assert definition["portfolio"]["weight_grid"] is False


def test_switch_targets_use_only_frozen_states() -> None:
    states = pd.DataFrame(
        {
            "signal_date": ["20260130", "20260227"],
            "trend_active": [True, False],
        }
    )

    targets = study.build_switch_targets(states)

    assert targets["20260130"] == study.ACTIVE_WEIGHTS
    assert targets["20260227"] == study.DEFENSIVE_WEIGHTS


def test_gate_rejects_without_static_drawdown_improvement() -> None:
    """切换若不能改善静态60/40回撤，则没有新增复杂度的价值。"""
    base = {
        "annualized_return": 0.15,
        "max_drawdown": -0.18,
        "sharpe": 1.10,
        "calmar": 0.80,
        "excess_return": 0.10,
        "annual_turnover": 1.0,
    }
    candidate = {
        key: dict(base)
        for key in [*study.FOLD_KEYS, "locked_test", "oos_full"]
    }
    metrics = {
        study.EXPERIMENT_ID: candidate,
        study.STATIC_ID: {
            key: {**base, "max_drawdown": -0.19}
            for key in candidate
        },
        study.SP500_ID: {
            key: {
                **base,
                "annualized_return": 0.13,
                "sharpe": 0.90,
                "max_drawdown": -0.25,
            }
            for key in candidate
        },
        study.STRESS_ID: {
            key: dict(base)
            for key in candidate
        },
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2019, 2027)
    }
    diagnostics = {
        "worst_day": -0.05,
        "expected_shortfall_95": -0.02,
        "quality_correlation": 0.20,
    }
    attribution = {"NASDAQ_GOLD_ACTIVE": {"day_share": 0.60}}

    gate = study.evaluate_gate(
        metrics,
        annual,
        diagnostics,
        attribution,
        {"passed": True},
    )

    assert gate["passed"] is False
    assert (
        gate["checks"]["drawdown_improvement_vs_static_at_least_2pct"]
        is False
    )


def test_same_fingerprint_skips_heavy_calculation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """同一数据版本再次研究必须直接复用，不重复加载大表。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        paths.monitoring_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    attempt = study.begin_research_attempt(
        study.RESEARCH_SPEC,
        paths=paths,
        data_as_of="20260728",
        data_version=study._data_version(paths),
    )
    study.complete_research_attempt(
        attempt,
        metrics={"gate": {"passed": False}},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中研究指纹后不得重新计算")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)

    result = study.run_study(paths, "20260728")

    assert result["reused"] is True
