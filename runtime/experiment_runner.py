"""最小实验运行器。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


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
    repository = SystemRepository(runtime_paths.system_state_path)
    repository.upsert_experiment(
        {
            "experiment_id": clean_id,
            "name": name or clean_id,
            "category": category,
            "status": "active",
            "owner": "Codex",
            "description": message,
            "config": config or {},
        }
    )
    timestamp = datetime.now().strftime("%H%M%S")
    run_id = f"{clean_id}:{target_date}:{timestamp}"
    output_dir = runtime_paths.runs_dir / "experiments" / clean_id / f"{target_date}-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.md"
    summary_path.write_text(
        _render_summary(name or clean_id, clean_id, target_date, config or {}, metrics or {}, message),
        encoding="utf-8",
    )
    (output_dir / "config.json").write_text(json.dumps(config or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "metrics.json").write_text(json.dumps(metrics or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    run = repository.record_experiment_run(
        experiment_id=clean_id,
        run_id=run_id,
        run_date=target_date,
        status="SUCCESS",
        output_dir=output_dir,
        config=config or {},
        metrics=metrics or {},
        message=message,
    )
    repository.record_experiment_artifact(run_id, "summary", summary_path, "实验摘要")
    repository.record_experiment_artifact(run_id, "config", output_dir / "config.json", "实验配置")
    repository.record_experiment_artifact(run_id, "metrics", output_dir / "metrics.json", "实验指标")
    return {
        "experiment_id": clean_id,
        "run_id": run_id,
        "run_date": target_date,
        "status": run["status"],
        "output_dir": str(output_dir),
        "summary_path": str(summary_path),
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
