"""黄金趋势国债切换研究测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from examples import gold_trend_bond_switch_study as study
from runtime.paths import RuntimePaths


def test_definition_freezes_gold_trend_and_bond_fallback() -> None:
    """研究语义必须是单一黄金趋势和国债兜底。"""
    definition = study.RESEARCH_SPEC.definition

    assert definition["signal"]["formula"] == "gold_ma60_gt_ma120"
    assert definition["portfolio"]["trend_active"] == {"518880.SH": 1.0}
    assert definition["portfolio"]["trend_inactive"] == {"511010.SH": 1.0}
    assert definition["risk_overlay"] == "none"


def test_state_attribution_applies_signal_on_next_trading_day() -> None:
    """月末状态只能从下一交易日起参与收益归因。"""
    calendar = list(pd.date_range("2024-01-29", periods=6, freq="B"))
    states = pd.DataFrame(
        {
            "signal_date": ["20240131", "20240202"],
            "trend_active": [True, False],
        }
    )

    class Result:
        daily_values = pd.Series(
            [100.0, 101.0, 102.0, 104.0, 103.0, 104.0],
            index=calendar,
        )

    class Run:
        result = Result()

    attribution = study.build_state_attribution(Run(), states, calendar)

    assert attribution["GOLD_ACTIVE"]["days"] == 2
    assert attribution["BOND_DEFENSIVE"]["days"] == 1


def test_gate_rejects_when_not_better_than_gold_bond_drawdown() -> None:
    """新增切换逻辑若不改善现有防守组合回撤就没有存在价值。"""
    metrics = {
        key: {
            "annualized_return": 0.08,
            "max_drawdown": -0.16,
            "sharpe": 1.0,
            "calmar": 0.50,
            "excess_return": 0.10,
            "annual_turnover": 1.0,
        }
        for key in [*study.FOLDS, "full"]
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2015, 2027)
    }
    comparison = {
        study.STRATEGY_ID: metrics["full"],
        "黄金单资产": {
            **metrics["full"],
            "annualized_return": 0.10,
            "max_drawdown": -0.30,
        },
        "黄金国债50/50": {
            **metrics["full"],
            "annualized_return": 0.07,
            "max_drawdown": -0.165,
            "sharpe": 0.92,
        },
    }
    attribution = {"GOLD_ACTIVE": {"day_share": 0.50}}

    gate = study.evaluate_gate(
        metrics,
        annual,
        0.20,
        comparison,
        attribution,
    )

    assert gate["passed"] is False
    assert (
        gate["checks"]["gold_bond_drawdown_improvement_at_least_2pct"]
        is False
    )


def test_same_fingerprint_skips_heavy_calculation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """同一口径和数据版本必须复用历史结论。"""
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
        data_as_of="20260724",
        data_version=study._data_version(paths),
    )
    study.complete_research_attempt(
        attempt,
        metrics={"gate": {"passed": False}},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中指纹后不得重新回测")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)

    result = study.run_study(paths, "20260724")

    assert result["reused"] is True
