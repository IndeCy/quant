from __future__ import annotations

from pathlib import Path

from examples import nasdaq_gold_bond_balanced_study as study
from runtime.paths import RuntimePaths


def test_definition_is_fixed_growth_defense_split() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["assets"]["weights"] == {
        "159941.SZ": 0.50,
        "518880.SH": 0.25,
        "511010.SH": 0.25,
    }
    assert definition["portfolio"]["weight_grid"] is False
    assert definition["portfolio"]["timing"] is False
    assert definition["portfolio"]["leverage"] == 1.0


def test_gate_requires_both_sp500_lift_and_nasdaq_gold_drawdown_improvement() -> None:
    base = {
        "annualized_return": 0.15,
        "max_drawdown": -0.17,
        "sharpe": 1.1,
        "calmar": 0.8,
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
            key: {**base, "annualized_return": 0.18, "max_drawdown": -0.18}
            for key in candidate
        },
        study.GLOBAL_ID: {
            key: {**base, "annualized_return": 0.10}
            for key in candidate
        },
        study.SP500_ID: {
            key: {**base, "annualized_return": 0.15}
            for key in candidate
        },
        study.STRESS_ID: {
            key: dict(base)
            for key in candidate
        },
    }
    annual = {
        str(year): {"annualized_return": 0.05}
        for year in range(2016, 2027)
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
    assert gate["checks"]["drawdown_improvement_vs_nasdaq_gold_at_least_2pct"] is False


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
