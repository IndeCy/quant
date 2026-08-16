"""跨因子研究稳健性元审计测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples import factor_research_meta_audit as audit


def test_collapse_version_families_keeps_latest_created_run() -> None:
    """同一研究家族只能保留最新版本，避免重复计票。"""
    runs = [
        {"experiment_id": "alpha_v1", "created_at": "2026-01-01"},
        {"experiment_id": "other_v1", "created_at": "2026-01-02"},
        {"experiment_id": "alpha_v2", "created_at": "2026-01-03"},
    ]

    result = audit.collapse_version_families(runs)

    assert [item["experiment_id"] for item in result] == ["alpha_v2", "other_v1"]


def test_select_current_runs_does_not_fallback_to_stale_family_version() -> None:
    """家族新版待复验时，不能退回旧版参与跨因子排名。"""
    common = {
        "current_definition_fingerprint": "same",
        "run_definition_fingerprint": "same",
    }
    runs = [
        {
            "experiment_id": "alpha_v1",
            "created_at": "2026-01-01",
            "experiment_status": "active",
            **common,
        },
        {
            "experiment_id": "alpha_v2",
            "created_at": "2026-01-03",
            "experiment_status": "needs_revalidation",
            **common,
        },
        {
            "experiment_id": "other_v1",
            "created_at": "2026-01-02",
            "experiment_status": "active",
            **common,
        },
    ]

    result = audit.select_current_runs(runs)

    assert [item["experiment_id"] for item in result] == ["other_v1"]


def test_summarize_decay_detects_validation_false_discovery() -> None:
    """验证期过门槛但锁定期失败必须计入乐观偏差。"""
    rows = [
        _row("A", 0.20, 1.0, 0.02, 0.1, True, False),
        _row("B", 0.10, 0.7, -0.05, -0.2, True, False),
        _row("C", -0.02, 0.0, 0.12, 0.8, False, True),
        _row("D", 0.03, 0.2, 0.01, 0.1, False, False),
    ]

    summary = audit.summarize_decay(rows)

    assert summary["validation_core_pass_count"] == 2
    assert summary["locked_core_pass_count"] == 1
    assert summary["validation_false_discovery_ratio"] == pytest.approx(1.0)
    assert summary["median_locked_return"] < summary["median_validation_return"]


def test_meta_audit_reuses_same_source_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """源运行集合不变时不得重复执行元分析。"""
    monkeypatch.setattr(
        audit,
        "load_source_manifest",
        lambda paths: [{"run_id": "r1", "run_fingerprint": "f1"}],
    )

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "decision": "REQUIRE_MULTI_FOLD"}

    monkeypatch.setattr(
        audit,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        audit,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复元分析"),
    )

    result = audit.run_study(audit.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _row(
    experiment_id: str,
    validation_return: float,
    validation_sharpe: float,
    locked_return: float,
    locked_sharpe: float,
    validation_pass: bool,
    locked_pass: bool,
) -> dict[str, object]:
    """构造元分析最小实验行。"""
    return {
        "experiment_id": experiment_id,
        "validation_return": validation_return,
        "locked_return": locked_return,
        "return_decay": locked_return - validation_return,
        "validation_sharpe": validation_sharpe,
        "locked_sharpe": locked_sharpe,
        "sharpe_decay": locked_sharpe - validation_sharpe,
        "validation_drawdown": -0.2,
        "locked_drawdown": -0.2,
        "locked_excess": 0.1,
        "full_turnover": 4.0,
        "quality_correlation": 0.5,
        "validation_core_pass": validation_pass,
        "locked_core_pass": locked_pass,
    }
