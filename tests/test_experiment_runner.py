"""Experiment Runner 测试。"""

from pathlib import Path

from runtime.experiment_runner import ExperimentArtifact, record_completed_experiment, run_manual_experiment
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


def test_completed_experiment_is_available_in_generic_list(tmp_path: Path) -> None:
    """自动研究实验必须复用通用登记入口并能被前端列表读取。"""
    paths = RuntimePaths(tmp_path / "runtime")
    output_dir = paths.runs_dir / "experiments" / "quality_ml_ranker_v0" / "20260722-001"
    output_dir.mkdir(parents=True)
    report = output_dir / "report.md"
    report.write_text("# Quality ML Ranker V0", encoding="utf-8")

    record_completed_experiment(
        paths=paths,
        experiment_id="quality_ml_ranker_v0",
        name="Quality ML Ranker V0",
        category="machine_learning",
        run_date="20260722",
        output_dir=output_dir,
        config={"selected_model_id": "hist_gbdt_v0"},
        metrics={"gate": {"status": "FAIL"}},
        message="not promoted",
        artifacts=[ExperimentArtifact("summary", report, "研究报告")],
        run_suffix="001",
    )

    experiments = SystemRepository(paths.system_state_path).list_experiments()

    assert experiments[0]["experiment_id"] == "quality_ml_ranker_v0"
    assert experiments[0]["latest_run_status"] == "SUCCESS"
    assert experiments[0]["latest_metrics"]["gate"]["status"] == "FAIL"


def test_experiment_repository_serves_latest_passed_daily_series(
    tmp_path: Path,
) -> None:
    """Dashboard只能查询最新通过门槛运行的结构化净值。"""
    paths = RuntimePaths(tmp_path / "runtime")
    repository = SystemRepository(paths.system_state_path)
    experiment_id = "allocation_research_v1"
    repository.upsert_experiment(
        {
            "experiment_id": experiment_id,
            "name": "Allocation Research V1",
            "category": "allocation",
            "status": "completed",
        }
    )
    run_id = f"{experiment_id}:20260728:001"
    repository.record_experiment_run(
        experiment_id=experiment_id,
        run_id=run_id,
        run_date="20260728",
        status="SUCCESS",
        output_dir=paths.runs_dir / "experiments" / experiment_id / "001",
        outcome="PASSED_RESEARCH_GATE",
        data_as_of="20260728",
    )
    repository.replace_experiment_series(
        run_id,
        experiment_id,
        [
            {
                "series_id": "candidate",
                "series_name": "候选组合",
                "trade_date": "20260727",
                "nav": 1.0,
                "adjust_policy": "qfq_m0_t1_5bps",
            },
            {
                "series_id": "candidate",
                "series_name": "候选组合",
                "trade_date": "20260728",
                "nav": 1.02,
                "adjust_policy": "qfq_m0_t1_5bps",
            },
        ],
    )

    series = repository.load_latest_experiment_series(
        experiment_id,
        series_ids=("candidate",),
    )

    assert series == [
        {
            "series_id": "candidate",
            "name": "候选组合",
            "adjust_policy": "qfq_m0_t1_5bps",
            "as_of": "20260728",
            "points": [
                {"trade_date": "20260727", "nav": 1.0},
                {"trade_date": "20260728", "nav": 1.02},
            ],
        }
    ]
