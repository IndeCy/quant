"""按 run_id 登记可再生运行产物。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from runtime.schema_version import apply_schema_migrations


ARTIFACT_TYPES = {
    "daily_report.md": "daily_report",
    "rebalance_plan.csv": "rebalance_plan",
    "portfolio_snapshot.csv": "portfolio_snapshot",
    "strategy_metrics.json": "strategy_metrics",
    "monthly_review.md": "monthly_review",
    "run_log.txt": "run_log",
}


class ArtifactRegistry:
    """运行产物索引只保存元数据，不把文件内容复制进状态库。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        apply_schema_migrations(self.database_path)

    def register_directory(self, run_id: str, directory: str | Path) -> list[dict[str, object]]:
        """登记目录中所有文件，返回写入的元数据。"""
        base = Path(directory)
        if not base.exists():
            return []
        registered: list[dict[str, object]] = []
        with sqlite3.connect(self.database_path) as con:
            for path in sorted(item for item in base.rglob("*") if item.is_file()):
                artifact_type = ARTIFACT_TYPES.get(path.name, path.suffix.lstrip(".") or "file")
                artifact_id = hashlib.sha256(f"{run_id}:{path}".encode("utf-8")).hexdigest()
                con.execute(
                    """
                    INSERT INTO run_artifacts(artifact_id, run_id, artifact_type, file_path, size_bytes)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, file_path) DO UPDATE SET
                        artifact_type=excluded.artifact_type,
                        size_bytes=excluded.size_bytes
                    """,
                    [artifact_id, run_id, artifact_type, str(path), path.stat().st_size],
                )
                registered.append({"artifact_type": artifact_type, "file_path": str(path)})
        return registered
