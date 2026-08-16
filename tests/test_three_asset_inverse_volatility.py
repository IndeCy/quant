"""三资产逆波动风险预算研究测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from examples import three_asset_inverse_volatility_study as study
from portfolio.inverse_volatility import build_inverse_volatility_targets
from runtime.paths import RuntimePaths


def test_inverse_volatility_uses_signal_day_and_prior_prices_only() -> None:
    """信号日后的价格变化不能反向修改已经形成的权重。"""
    index = pd.date_range("2024-01-01", periods=100, freq="B")
    close = pd.DataFrame(
        {
            "A": 100.0 + pd.Series(range(100), index=index) * 0.1,
            "B": 100.0 + pd.Series(range(100), index=index) * 0.2,
            "C": 100.0 + pd.Series(range(100), index=index) * 0.3,
        },
        index=index,
    )
    signal = index[70]
    original, _ = build_inverse_volatility_targets(
        close,
        [signal],
        ["A", "B", "C"],
        lookback_days=20,
    )
    close.loc[index[71]:, "A"] *= 3.0
    changed, _ = build_inverse_volatility_targets(
        close,
        [signal],
        ["A", "B", "C"],
        lookback_days=20,
    )

    assert original == changed


def test_lower_volatility_receives_higher_weight() -> None:
    """组合层必须把更低波动资产分配为更高目标权重。"""
    index = pd.date_range("2024-01-01", periods=80, freq="B")
    increments = pd.Series(
        [(-1) ** i for i in range(80)],
        index=index,
        dtype=float,
    )
    close = pd.DataFrame(
        {
            "LOW": 100.0 + increments.cumsum() * 0.1,
            "MID": 100.0 + increments.cumsum() * 0.5,
            "HIGH": 100.0 + increments.cumsum() * 1.0,
        },
        index=index,
    )

    targets, _ = build_inverse_volatility_targets(
        close,
        [index[-1]],
        ["LOW", "MID", "HIGH"],
        lookback_days=60,
    )
    weights = targets[index[-1].strftime("%Y%m%d")]

    assert weights["LOW"] > weights["MID"] > weights["HIGH"]
    assert abs(sum(weights.values()) - 1.0) < 1e-12


def test_definition_freezes_window_and_disables_overlay() -> None:
    """研究定义不能在看到结果后切换窗口、加杠杆或叠加择时。"""
    definition = study.RESEARCH_SPEC.definition

    assert definition["portfolio"]["lookback_trading_days"] == 60
    assert definition["portfolio"]["leverage"] == 1.0
    assert definition["portfolio"]["weight_cap"] is None
    assert definition["risk_overlay"] == "none"


def test_gate_rejects_insufficient_drawdown_improvement() -> None:
    """相对黄金国债的回撤改善不足3个百分点时必须淘汰。"""
    metrics = {
        key: {
            "annualized_return": 0.06,
            "max_drawdown": -0.14,
            "sharpe": 0.95,
            "calmar": 0.43,
            "excess_return": 0.10,
            "annual_turnover": 0.5,
        }
        for key in [*study.FOLDS, "full"]
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2015, 2027)
    }
    comparison = {
        study.STRATEGY_ID: metrics["full"],
        "黄金国债50/50": {
            **metrics["full"],
            "annualized_return": 0.07,
            "max_drawdown": -0.16,
            "sharpe": 0.92,
        },
    }
    weights = {
        symbol: {"average_weight": 1.0 / 3.0}
        for symbol in study.ASSETS
    }

    gate = study.evaluate_gate(metrics, annual, 0.20, comparison, weights)

    assert gate["passed"] is False
    assert (
        gate["checks"]["drawdown_improvement_vs_gold_bond_at_least_3pct"]
        is False
    )


def test_same_fingerprint_reuses_result_before_panel_loading(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同研究与数据版本再次运行时不得加载基金行情。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        paths.monitoring_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    data_version = study._data_version(paths)
    attempt = study.begin_research_attempt(
        study.RESEARCH_SPEC,
        paths=paths,
        data_as_of="20260724",
        data_version=data_version,
    )
    study.complete_research_attempt(
        attempt,
        metrics={"gate": {"passed": False}},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_loaded(*_args, **_kwargs):
        raise AssertionError("命中研究指纹后不应加载基金大表")

    monkeypatch.setattr(study, "_calculate", fail_if_loaded)

    result = study.run_study(paths, "20260724")

    assert result["reused"] is True
