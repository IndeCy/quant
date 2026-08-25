"""最小实验运行器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


@dataclass(frozen=True)
class ExperimentArtifact:
    """一个已经落盘、等待登记的实验产物。"""

    artifact_type: str
    path: Path
    title: str


def run_manual_experiment(
    paths: RuntimePaths | None = None,
    experiment_id: str = "",
    name: str = "",
    category: str = "manual",
    run_date: str | None = None,
    config: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    message: str = "",
) -> dict[str, Any]:
    """登记一次手工实验，作为后续自动实验 runner 的最小基座。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    target_date = run_date or datetime.now().strftime("%Y%m%d")
    clean_id = experiment_id.strip()
    if not clean_id:
        raise ValueError("experiment_id is required")
    timestamp = datetime.now().strftime("%H%M%S")
    output_dir = runtime_paths.runs_dir / "experiments" / clean_id / f"{target_date}-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.md"
    summary_path.write_text(
        _render_summary(name or clean_id, clean_id, target_date, config or {}, metrics or {}, message),
        encoding="utf-8",
    )
    (output_dir / "config.json").write_text(json.dumps(config or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "metrics.json").write_text(json.dumps(metrics or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    return record_completed_experiment(
        paths=runtime_paths,
        experiment_id=clean_id,
        name=name or clean_id,
        category=category,
        run_date=target_date,
        output_dir=output_dir,
        config=config or {},
        metrics=metrics or {},
        message=message,
        artifacts=[
            ExperimentArtifact("summary", summary_path, "实验摘要"),
            ExperimentArtifact("config", output_dir / "config.json", "实验配置"),
            ExperimentArtifact("metrics", output_dir / "metrics.json", "实验指标"),
        ],
        run_suffix=timestamp,
    )


def record_completed_experiment(
    *,
    paths: RuntimePaths | None,
    experiment_id: str,
    name: str,
    category: str,
    run_date: str,
    output_dir: Path,
    config: dict[str, Any],
    metrics: dict[str, Any],
    message: str,
    artifacts: list[ExperimentArtifact],
    run_suffix: str | None = None,
) -> dict[str, Any]:
    """统一登记任意已完成实验，研究类型不得另建持久化入口。"""
    runtime_paths = paths or get_runtime_paths()
    clean_id = experiment_id.strip()
    if not clean_id or not name.strip():
        raise ValueError("experiment_id and name are required")
    missing = [str(artifact.path) for artifact in artifacts if not artifact.path.exists()]
    if missing:
        raise FileNotFoundError(f"experiment artifacts missing: {missing}")
    suffix = run_suffix or datetime.now().strftime("%H%M%S")
    run_id = f"{clean_id}:{run_date}:{suffix}"
    repository = SystemRepository(runtime_paths.system_state_path)
    repository.upsert_experiment(
        {
            "experiment_id": clean_id,
            "name": name,
            "category": category,
            "status": "active",
            "owner": "Codex",
            "description": message,
            "config": config,
        }
    )
    run = repository.record_experiment_run(
        experiment_id=clean_id,
        run_id=run_id,
        run_date=run_date,
        status="SUCCESS",
        output_dir=output_dir,
        config=config,
        metrics=metrics,
        message=message,
    )
    for artifact in artifacts:
        repository.record_experiment_artifact(
            run_id,
            artifact.artifact_type,
            artifact.path,
            artifact.title,
        )
    return {
        "experiment_id": clean_id,
        "run_id": run_id,
        "run_date": run_date,
        "status": run["status"],
        "output_dir": str(output_dir),
        "summary_path": str(next((item.path for item in artifacts if item.artifact_type == "summary"), "")),
    }


def _render_summary(
    name: str,
    experiment_id: str,
    run_date: str,
    config: dict[str, Any],
    metrics: dict[str, Any],
    message: str,
) -> str:
    return "\n".join(
        [
            f"# {name}",
            "",
            f"- 实验ID：{experiment_id}",
            f"- 运行日期：{run_date}",
            f"- 说明：{message or '无'}",
            "",
            "## Config",
            "",
            "```json",
            json.dumps(config, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Metrics",
            "",
            "```json",
            json.dumps(metrics, ensure_ascii=False, indent=2),
            "```",
        ]
    )
