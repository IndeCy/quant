"""研究尝试去重和可回溯测试。"""

from pathlib import Path
import sqlite3

import pytest

from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.research_attempts import (
    ResearchAlreadyRunningError,
    ResearchSpec,
    begin_research_attempt,
    build_run_fingerprint,
    complete_research_attempt,
    fail_research_attempt,
    research_fingerprint,
)


def _spec(experiment_id: str = "quality_lowbeta_v0") -> ResearchSpec:
    return ResearchSpec(
        experiment_id=experiment_id,
        name="Quality LowBeta V0",
        category="factor_strategy",
        hypothesis="低 Beta 能否改善 Quality 的回撤",
        definition={
            "factors": ["roa", "ocf_to_or", "low_beta_120d", "low_volatility_60d"],
            "top_n": 40,
            "rebalance": "monthly",
            "execution": {"lag": 1, "adjust": "qfq"},
        },
    )


def test_research_fingerprint_is_stable_and_excludes_display_identity() -> None:
    """键顺序和实验展示名称不能制造一次新计算。"""
    left = {"top_n": 40, "factors": ["roa", "ocf"]}
    right = {"factors": ["roa", "ocf"], "top_n": 40}

    assert research_fingerprint(left) == research_fingerprint(right)
    assert build_run_fingerprint(research_fingerprint(left), "2026-07-22") == (
        build_run_fingerprint(research_fingerprint(right), "20260722")
    )


def test_completed_attempt_is_reused_without_recalculation(tmp_path: Path) -> None:
    """相同定义和数据截止日应复用结果，并累计节省次数。"""
    paths = RuntimePaths(tmp_path / "runtime")
    first = begin_research_attempt(_spec(), paths=paths, data_as_of="20260722")
    summary = first.output_dir / "summary.md"
    summary.write_text("# rejected", encoding="utf-8")
    complete_research_attempt(
        first,
        metrics={"annualized_return": 0.0274, "gate": {"status": "FAIL"}},
        outcome="REJECTED",
        decision_reason="固定晋级门槛未通过",
        artifacts=[ExperimentArtifact("summary", summary, "研究报告")],
    )

    second = begin_research_attempt(_spec(), paths=paths, data_as_of="20260722")
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        "quality_lowbeta_v0"
    )

    assert second.should_run is False
    assert second.cached_result()["annualized_return"] == pytest.approx(0.0274)
    assert detail is not None
    assert detail["latest_run"]["reuse_count"] == 1
    assert detail["latest_run"]["outcome"] == "REJECTED"
    with sqlite3.connect(paths.system_state_path) as con:
        event = con.execute(
            "SELECT requested_experiment_id FROM research_attempt_reuse_events"
        ).fetchone()
    assert event == ("quality_lowbeta_v0",)


def test_same_computation_with_new_name_reuses_original_run(tmp_path: Path) -> None:
    """换实验 ID 不能绕过去重门禁，研究页仍要留下复用关系。"""
    paths = RuntimePaths(tmp_path / "runtime")
    original = begin_research_attempt(_spec(), paths=paths, data_as_of="20260722")
    complete_research_attempt(
        original,
        metrics={"sharpe": 0.245},
        outcome="REJECTED",
        decision_reason="风险收益不达标",
    )

    alias = begin_research_attempt(
        _spec("renamed_lowbeta"),
        paths=paths,
        data_as_of="20260722",
    )
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        "renamed_lowbeta"
    )

    assert alias.should_run is False
    assert alias.reused_run is not None
    assert alias.reused_run["experiment_id"] == "quality_lowbeta_v0"
    assert detail is not None
    assert detail["latest_run"]["status"] == "REUSED"
    assert detail["latest_run"]["reused_from_run_id"] == original.run_id


def test_new_data_or_force_allows_a_new_attempt(tmp_path: Path) -> None:
    """新增数据可自然复验，force 只绕过历史成功结果而不改定义。"""
    paths = RuntimePaths(tmp_path / "runtime")
    first = begin_research_attempt(_spec(), paths=paths, data_as_of="20260722")
    complete_research_attempt(
        first,
        metrics={"sharpe": 0.2},
        outcome="REJECTED",
        decision_reason="not enough",
    )

    new_data = begin_research_attempt(_spec(), paths=paths, data_as_of="20260723")
    fail_research_attempt(new_data, RuntimeError("fixture stop"))
    forced = begin_research_attempt(
        _spec(),
        paths=paths,
        data_as_of="20260722",
        force=True,
    )

    assert new_data.should_run is True
    assert new_data.run_fingerprint != first.run_fingerprint
    assert forced.should_run is True
    assert forced.run_fingerprint == first.run_fingerprint


def test_running_attempt_blocks_parallel_duplicate(tmp_path: Path) -> None:
    """同一研究运行中时必须拒绝第二份并发计算。"""
    paths = RuntimePaths(tmp_path / "runtime")
    begin_research_attempt(_spec(), paths=paths, data_as_of="20260722")

    with pytest.raises(ResearchAlreadyRunningError):
        begin_research_attempt(_spec(), paths=paths, data_as_of="20260722")


def test_failed_attempt_can_be_retried(tmp_path: Path) -> None:
    """失败记录可追踪，但不能永久阻断修复后的重试。"""
    paths = RuntimePaths(tmp_path / "runtime")
    failed = begin_research_attempt(_spec(), paths=paths, data_as_of="20260722")
    fail_research_attempt(failed, ValueError("broken input"))

    retry = begin_research_attempt(_spec(), paths=paths, data_as_of="20260722")

    assert retry.should_run is True
    assert retry.run_id != failed.run_id
