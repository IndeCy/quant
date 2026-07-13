"""Experiment Runner 测试。"""

from pathlib import Path

from runtime.experiment_runner import run_manual_experiment
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_experiment_repository_registers_definition_run_and_artifact(tmp_path: Path) -> None:
    """实验系统应能登记定义、运行和产物。"""
    paths = RuntimePaths(tmp_path / "runtime")
    repository = SystemRepository(paths.system_state_path)

    experiment = repository.upsert_experiment(
        {
            "experiment_id": "quality_walk_forward_research",
            "name": "Quality Walk Forward Research",
            "category": "validation",
            "status": "draft",
            "owner": "Codex",
            "description": "验证 Quality 风险层参数稳健性",
            "config": {"strategy_id": "quality_overlay"},
        }
    )
    run = repository.record_experiment_run(
        experiment_id="quality_walk_forward_research",
        run_id="quality_walk_forward_research:20260702:001",
        run_date="20260702",
        status="SUCCESS",
        output_dir=paths.runs_dir / "experiments" / "quality_walk_forward_research" / "20260702-001",
        config={"train": "2015-2021", "validate": "2022-2026"},
        metrics={"sharpe": 0.78},
        message="ok",
    )
    artifact = repository.record_experiment_artifact(
        run_id=run["run_id"],
        artifact_type="summary",
        file_path=Path(run["output_dir"]) / "summary.md",
        title="实验摘要",
    )
    detail = repository.load_experiment_detail("quality_walk_forward_research")

    assert experiment["experiment_id"] == "quality_walk_forward_research"
    assert run["status"] == "SUCCESS"
    assert artifact["artifact_type"] == "summary"
    assert detail is not None
    assert detail["latest_run"]["run_id"] == run["run_id"]
    assert detail["runs"][0]["metrics"]["sharpe"] == 0.78
    assert detail["runs"][0]["artifacts"][0]["title"] == "实验摘要"


def test_manual_experiment_runner_writes_summary_and_registers_run(tmp_path: Path) -> None:
    """最小 CLI 背后的 runner 应生成可回溯实验产物。"""
    paths = RuntimePaths(tmp_path / "runtime")

    result = run_manual_experiment(
        paths=paths,
        experiment_id="manual_quality_note",
        name="Manual Quality Note",
        category="research_note",
        run_date="20260702",
        config={"strategy_id": "quality_overlay"},
        metrics={"annual_return": 0.1587},
        message="manual registration",
    )
    repository = SystemRepository(paths.system_state_path)
    detail = repository.load_experiment_detail("manual_quality_note")
    summary_path = Path(result["summary_path"])

    assert result["status"] == "SUCCESS"
    assert summary_path.exists()
    assert "Manual Quality Note" in summary_path.read_text(encoding="utf-8")
    assert detail is not None
    assert detail["latest_run"]["metrics"]["annual_return"] == 0.1587
