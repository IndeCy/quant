"""研究实验 API 的查询与安全预览能力。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


class ExperimentApiMixin:
    """把通用实验查询从主 API 服务中隔离，避免服务类持续膨胀。"""

    paths: RuntimePaths
    system_repository: SystemRepository

    def experiments(self) -> list[dict[str, Any]]:
        """返回全部研究实验及其最近一次运行摘要。"""
        return self.system_repository.list_experiments()

    def experiment_detail(self, experiment_id: str) -> dict[str, Any] | None:
        """返回实验运行历史和已登记产物。"""
        detail = self.system_repository.load_experiment_detail(experiment_id)
        if detail is None:
            return None
        latest_run = detail.get("latest_run")
        if isinstance(latest_run, dict):
            latest_run["artifacts"] = [
                self._attach_experiment_preview(artifact)
                for artifact in latest_run.get("artifacts", [])
                if isinstance(artifact, dict)
            ]
        return detail

    def _attach_experiment_preview(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """仅预览 runs 目录内的小型文本产物，避免 API 任意读取本机文件。"""
        result = dict(artifact)
        file_path = Path(str(result.get("file_path") or "")).expanduser().resolve()
        runs_dir = self.paths.runs_dir.resolve()
        if file_path.suffix.lower() not in {".md", ".json", ".txt"} or not file_path.is_relative_to(runs_dir):
            return result
        try:
            result["preview"] = file_path.read_text(encoding="utf-8")[:200_000]
        except (OSError, UnicodeError):
            return result
        return result
