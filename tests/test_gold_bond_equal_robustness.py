"""黄金国债等权鲁棒性门槛与指纹复用测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples import gold_bond_equal_robustness_study as study


def _metric() -> dict[str, float]:
    return {
        "annualized_return": 0.08,
        "max_drawdown": -0.15,
        "sharpe": 0.90,
        "annual_turnover": 0.30,
    }


def test_gate_rejects_quarterly_frequency_instability() -> None:
    """季度再平衡若与月频结果差异过大，基础结论不够稳健。"""
    metrics = {
        study.BASELINE_ID: _metric(),
        study.STRESS_20_ID: _metric(),
        study.QUARTERLY_ID: {
            **_metric(),
            "annualized_return": 0.065,
        },
        study.BOND_ONLY_ID: _metric(),
    }
    rolling = {"2015_2017": _metric()}
    correlations = {"full": 0.10}

    gate = study.evaluate_gate(metrics, rolling, correlations, 0.10)

    assert gate["passed"] is False
    assert gate["checks"]["quarterly_return_difference_within_1pct"] is False


def test_same_fingerprint_reuses_before_panel_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同鲁棒性定义和数据版本必须在基金面板读取前复用。"""
    for path in [
        tmp_path / "data" / "etf_lof_reits_daily_adj_20041220_20260617.duckdb",
        tmp_path / "data" / "benchmark_increment.duckdb",
        tmp_path / "data" / "monitoring.sqlite3",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应读取基金面板"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True
