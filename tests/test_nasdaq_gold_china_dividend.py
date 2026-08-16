"""纳指黄金红利低波固定等权研究测试。"""

from __future__ import annotations

from pathlib import Path

from examples import nasdaq_gold_china_dividend_study as study
from runtime.paths import RuntimePaths


def test_definition_is_fixed_equal_weight_without_timing() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["assets"]["weights"] == {
        "159941.SZ": 1 / 3,
        "518880.SH": 1 / 3,
        "512890.SH": 1 / 3,
    }
    assert definition["portfolio"]["weight_grid"] is False
    assert definition["portfolio"]["timing"] is False
    assert definition["portfolio"]["rebalance"] == "monthly"


def test_gate_rejects_when_return_does_not_clear_sp500() -> None:
    base = {
        "annualized_return": 0.12,
        "max_drawdown": -0.18,
        "sharpe": 1.0,
        "calmar": 0.65,
        "excess_return": 0.10,
        "annual_turnover": 0.4,
    }
    candidate = {
        key: dict(base)
        for key in [*study.FOLD_KEYS, "locked_test", "full"]
    }
    metrics = {
        study.EXPERIMENT_ID: candidate,
        study.NASDAQ_GOLD_ID: {
            key: {**base, "annualized_return": 0.15}
            for key in candidate
        },
        study.GLOBAL_ID: {
            key: {**base, "annualized_return": 0.10}
            for key in candidate
        },
        study.SP500_ID: {
            key: {**base, "annualized_return": 0.13, "sharpe": 0.80}
            for key in candidate
        },
        study.STRESS_ID: {
            key: dict(base)
            for key in candidate
        },
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2020, 2027)
    }
    diagnostics = {
        "worst_day": -0.05,
        "expected_shortfall_95": -0.02,
        "quality_correlation": 0.20,
    }

    gate = study.evaluate_gate(
        metrics,
        annual,
        diagnostics,
        {"passed": True},
    )

    assert gate["passed"] is False
    assert gate["checks"]["return_lift_vs_sp500_at_least_05pct"] is False


def test_same_fingerprint_skips_heavy_calculation(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
        raise AssertionError("命中研究指纹后不得重复计算")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)

    result = study.run_study(paths, "20260728")

    assert result["reused"] is True
