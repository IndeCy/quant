"""实验管理仓库方法。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ExperimentRepositoryMixin:
    """提供研究实验定义、运行和产物登记能力。"""

    def upsert_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        """登记实验定义。"""
        experiment_id = str(payload.get("experiment_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not experiment_id or not name:
            raise ValueError("experiment_id and name are required")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO experiments(
                    experiment_id, name, category, status, owner, description, config_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    status=excluded.status,
                    owner=excluded.owner,
                    description=excluded.description,
                    config_json=excluded.config_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    experiment_id,
                    name,
                    str(payload.get("category") or "research"),
                    str(payload.get("status") or "draft"),
                    str(payload.get("owner") or ""),
                    str(payload.get("description") or ""),
                    json.dumps(dict(payload.get("config") or {}), ensure_ascii=False, sort_keys=True),
                ],
            )
            row = con.execute("SELECT * FROM experiments WHERE experiment_id = ?", [experiment_id]).fetchone()
        return self._row_to_dict(row)

    def record_experiment_run(
        self,
        experiment_id: str,
        run_id: str,
        run_date: str,
        status: str,
        output_dir: str | Path,
        config: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any]:
        """登记一次实验运行。"""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO experiment_runs(
                    run_id, experiment_id, run_date, status, output_dir,
                    config_json, metrics_json, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    output_dir=excluded.output_dir,
                    config_json=excluded.config_json,
                    metrics_json=excluded.metrics_json,
                    message=excluded.message,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    run_id,
                    experiment_id,
                    run_date,
                    status,
                    str(output_dir),
                    json.dumps(config or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(metrics or {}, ensure_ascii=False, sort_keys=True),
                    message,
                ],
            )
            row = con.execute("SELECT * FROM experiment_runs WHERE run_id = ?", [run_id]).fetchone()
        return self._row_to_dict(row)

    def record_experiment_artifact(
        self,
        run_id: str,
        artifact_type: str,
        file_path: str | Path,
        title: str,
    ) -> dict[str, Any]:
        """登记实验产物。"""
        path = Path(file_path)
        artifact_id = f"{run_id}:{artifact_type}:{path.name}"
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO experiment_artifacts(
                    artifact_id, run_id, artifact_type, file_path, title
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    artifact_type=excluded.artifact_type,
                    file_path=excluded.file_path,
                    title=excluded.title,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [artifact_id, run_id, artifact_type, str(path), title],
            )
            row = con.execute("SELECT * FROM experiment_artifacts WHERE artifact_id = ?", [artifact_id]).fetchone()
        return self._row_to_dict(row)

    def load_experiment_detail(self, experiment_id: str) -> dict[str, Any] | None:
        """读取实验定义、运行和产物。"""
        with self._connect() as con:
            experiment = con.execute("SELECT * FROM experiments WHERE experiment_id = ?", [experiment_id]).fetchone()
            if experiment is None:
                return None
            runs = con.execute(
                """
                SELECT * FROM experiment_runs
                WHERE experiment_id = ?
                ORDER BY run_date DESC, created_at DESC
                """,
                [experiment_id],
            ).fetchall()
            run_ids = [str(row["run_id"]) for row in runs]
            artifacts_by_run: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                artifact_rows = con.execute(
                    f"SELECT * FROM experiment_artifacts WHERE run_id IN ({placeholders}) ORDER BY artifact_type, title",
                    run_ids,
                ).fetchall()
                for row in artifact_rows:
                    item = self._row_to_dict(row)
                    artifacts_by_run[str(item["run_id"])].append(item)
        result = self._row_to_dict(experiment)
        result["runs"] = []
        for row in runs:
            item = self._row_to_dict(row)
            item["artifacts"] = artifacts_by_run.get(str(item["run_id"]), [])
            result["runs"].append(item)
        result["latest_run"] = result["runs"][0] if result["runs"] else None
        return result
