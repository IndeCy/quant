"""三资产固定等权研究的语义、门槛与去重测试。"""

from __future__ import annotations

from pathlib import Path

from examples import three_asset_equal_all_weather_study as study
from runtime.paths import RuntimePaths


def test_definition_is_fixed_equal_weight_without_overlay() -> None:
    """资产权重必须在回测前固定，不能暗中做趋势或风险择时。"""
    weights = study.RESEARCH_SPEC.definition["asset_allocation"]

    assert set(weights) == {"510300.SH", "518880.SH", "511010.SH"}
    assert all(abs(weight - 1.0 / 3.0) < 1e-12 for weight in weights.values())
    assert study.RESEARCH_SPEC.definition["risk_overlay"] == "none"
    assert study.RESEARCH_SPEC.definition["portfolio"]["rebalance"] == "monthly"


def test_gate_rejects_candidate_without_gold_bond_return_uplift() -> None:
    """加入权益后若没有增加收益，就没有替代纯防守组合的价值。"""
    metrics = {
        key: {
            "annualized_return": 0.075,
            "max_drawdown": -0.20,
            "sharpe": 0.85,
            "calmar": 0.375,
            "excess_return": 0.10,
            "annual_turnover": 0.3,
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
            "annualized_return": 0.074,
            "max_drawdown": -0.16,
            "sharpe": 0.90,
        },
        "沪深300单资产": {
            **metrics["full"],
            "max_drawdown": -0.40,
        },
    }

    gate = study.evaluate_gate(metrics, annual, 0.30, comparison)

    assert gate["passed"] is False
    assert (
        gate["checks"]["return_uplift_vs_gold_bond_at_least_05pct"]
        is False
    )


def test_reused_fingerprint_skips_panel_loading(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同定义和数据版本第二次运行不得重复加载基金大表。"""
    paths = _seed_paths(tmp_path)
    monkeypatch.setattr(study, "_require_feasibility_passed", lambda _: None)
    calculation = {
        "strategy_id": study.STRATEGY_ID,
        "gate": {"passed": False, "checks": {}},
        "latest_holdings": [],
        "report_path": str(tmp_path / "report.md"),
    }

    def fake_calculate(_paths, _as_of):
        raise AssertionError("首次运行由测试直接登记，不调用真实计算")

    monkeypatch.setattr(study, "_calculate", fake_calculate)
    attempt = study.begin_research_attempt(
        study.RESEARCH_SPEC,
        paths=paths,
        data_as_of="20260724",
        data_version=study._data_version(paths),
    )
    assert attempt.should_run is True
    study.complete_research_attempt(
        attempt,
        metrics=calculation,
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    result = study.run_study(paths, "20260724")

    assert result["reused"] is True


def _seed_paths(tmp_path: Path) -> RuntimePaths:
    """创建只满足指纹计算的最小运行目录。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        paths.monitoring_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return paths
