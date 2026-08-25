"""实验管理仓库方法。"""

from __future__ import annotations

import json
import math
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
                    experiment_id, name, category, status, owner, description,
                    hypothesis, definition_fingerprint, config_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    status=excluded.status,
                    owner=excluded.owner,
                    description=excluded.description,
                    hypothesis=CASE
                        WHEN excluded.hypothesis <> '' THEN excluded.hypothesis
                        ELSE experiments.hypothesis
                    END,
                    definition_fingerprint=CASE
                        WHEN excluded.definition_fingerprint <> '' THEN excluded.definition_fingerprint
                        ELSE experiments.definition_fingerprint
                    END,
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
                    str(payload.get("hypothesis") or ""),
                    str(payload.get("definition_fingerprint") or ""),
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
        *,
        definition_fingerprint: str = "",
        run_fingerprint: str = "",
        data_as_of: str = "",
        data_version: str = "",
        outcome: str = "",
        decision_reason: str = "",
        reused_from_run_id: str = "",
    ) -> dict[str, Any]:
        """登记一次实验运行。"""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO experiment_runs(
                    run_id, experiment_id, run_date, status, output_dir,
                    config_json, metrics_json, message, definition_fingerprint,
                    run_fingerprint, data_as_of, data_version, outcome, decision_reason,
                    reused_from_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    output_dir=excluded.output_dir,
                    config_json=excluded.config_json,
                    metrics_json=excluded.metrics_json,
                    message=excluded.message,
                    definition_fingerprint=excluded.definition_fingerprint,
                    run_fingerprint=excluded.run_fingerprint,
                    data_as_of=excluded.data_as_of,
                    data_version=excluded.data_version,
                    outcome=excluded.outcome,
                    decision_reason=excluded.decision_reason,
                    reused_from_run_id=excluded.reused_from_run_id,
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
                    definition_fingerprint,
                    run_fingerprint,
                    data_as_of,
                    data_version,
                    outcome,
                    decision_reason,
                    reused_from_run_id,
                ],
            )
            row = con.execute("SELECT * FROM experiment_runs WHERE run_id = ?", [run_id]).fetchone()
        return self._row_to_dict(row)

    def find_reusable_experiment_run(self, run_fingerprint: str) -> dict[str, Any] | None:
        """查找相同研究定义、相同数据快照下已经成功完成的运行。"""
        if not run_fingerprint:
            return None
        with self._connect() as con:
            row = con.execute(
                """
                SELECT * FROM experiment_runs
                WHERE run_fingerprint = ? AND status = 'SUCCESS'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [run_fingerprint],
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def find_running_experiment(self, run_fingerprint: str) -> dict[str, Any] | None:
        """查找同一运行指纹下尚未结束的任务，避免并发重复计算。"""
        if not run_fingerprint:
            return None
        with self._connect() as con:
            row = con.execute(
                """
                SELECT * FROM experiment_runs
                WHERE run_fingerprint = ? AND status = 'RUNNING'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [run_fingerprint],
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def mark_experiment_run_reused(
        self,
        run_id: str,
        requested_experiment_id: str = "",
    ) -> dict[str, Any]:
        """记录一次被去重门禁拦截的请求，量化节省的重复计算。"""
        with self._connect() as con:
            source = con.execute(
                "SELECT run_fingerprint, experiment_id FROM experiment_runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
            if source is None:
                raise KeyError(f"experiment run not found: {run_id}")
            con.execute(
                """
                UPDATE experiment_runs
                SET reuse_count=reuse_count + 1,
                    last_reused_at=CURRENT_TIMESTAMP,
                    modified_at=CURRENT_TIMESTAMP
                WHERE run_id = ?
                """,
                [run_id],
            )
            con.execute(
                """
                INSERT INTO research_attempt_reuse_events(
                    event_id, source_run_id, requested_experiment_id, run_fingerprint
                ) VALUES (lower(hex(randomblob(16))), ?, ?, ?)
                """,
                [
                    run_id,
                    requested_experiment_id or str(source["experiment_id"]),
                    str(source["run_fingerprint"]),
                ],
            )
            row = con.execute("SELECT * FROM experiment_runs WHERE run_id = ?", [run_id]).fetchone()
        return self._row_to_dict(row)

    def annotate_experiment_run(
        self,
        run_id: str,
        *,
        definition_fingerprint: str,
        run_fingerprint: str,
        data_as_of: str,
        data_version: str = "",
        outcome: str = "",
        decision_reason: str = "",
    ) -> dict[str, Any]:
        """为旧实验补充研究身份，不改写原指标和产物。"""
        with self._connect() as con:
            con.execute(
                """
                UPDATE experiment_runs
                SET definition_fingerprint=?,
                    run_fingerprint=?,
                    data_as_of=?,
                    data_version=?,
                    outcome=?,
                    decision_reason=?,
                    modified_at=CURRENT_TIMESTAMP
                WHERE run_id=?
                """,
                [
                    definition_fingerprint,
                    run_fingerprint,
                    data_as_of,
                    data_version,
                    outcome,
                    decision_reason,
                    run_id,
                ],
            )
            row = con.execute("SELECT * FROM experiment_runs WHERE run_id = ?", [run_id]).fetchone()
        if row is None:
            raise KeyError(f"experiment run not found: {run_id}")
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

    def replace_experiment_series(
        self,
        run_id: str,
        experiment_id: str,
        rows: list[dict[str, Any]],
    ) -> int:
        """原子替换单次实验的结构化日净值，供通用查询层使用。"""
        normalized: list[tuple[str, str, str, str, str, float, str]] = []
        for row in rows:
            series_id = str(row.get("series_id") or "").strip()
            series_name = str(row.get("series_name") or "").strip()
            trade_date = str(row.get("trade_date") or "").strip()
            nav = float(row.get("nav") or 0.0)
            if not series_id or not series_name:
                raise ValueError("series_id and series_name are required")
            if len(trade_date) != 8 or not trade_date.isdigit():
                raise ValueError(f"invalid experiment series date: {trade_date}")
            if not math.isfinite(nav) or nav <= 0:
                raise ValueError(f"invalid experiment series nav: {nav}")
            normalized.append(
                (
                    run_id,
                    experiment_id,
                    series_id,
                    series_name,
                    trade_date,
                    nav,
                    str(row.get("adjust_policy") or ""),
                )
            )
        with self._connect() as con:
            run = con.execute(
                "SELECT experiment_id FROM experiment_runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
            if run is None:
                raise KeyError(f"experiment run not found: {run_id}")
            if str(run["experiment_id"]) != experiment_id:
                raise ValueError("experiment series run does not match experiment")
            con.execute(
                "DELETE FROM experiment_series_daily WHERE run_id = ?",
                [run_id],
            )
            con.executemany(
                """
                INSERT INTO experiment_series_daily(
                    run_id, experiment_id, series_id, series_name,
                    trade_date, nav, adjust_policy
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                normalized,
            )
        return len(normalized)

    def load_latest_experiment_series(
        self,
        experiment_id: str,
        *,
        series_ids: tuple[str, ...] = (),
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """读取最新通过研究门槛运行的结构化日净值。"""
        safe_limit = max(2, min(int(limit), 5000))
        with self._connect() as con:
            run = con.execute(
                """
                SELECT run_id, data_as_of
                FROM experiment_runs
                WHERE experiment_id = ?
                  AND status = 'SUCCESS'
                  AND outcome = 'PASSED_RESEARCH_GATE'
                ORDER BY run_date DESC, created_at DESC
                LIMIT 1
                """,
                [experiment_id],
            ).fetchone()
            if run is None:
                return []
            parameters: list[Any] = [str(run["run_id"])]
            series_filter = ""
            if series_ids:
                placeholders = ",".join("?" for _ in series_ids)
                series_filter = f"AND series_id IN ({placeholders})"
                parameters.extend(series_ids)
            parameters.append(safe_limit)
            rows = con.execute(
                f"""
                WITH ranked AS (
                    SELECT *,
                           ROW_NUMBER() OVER(
                               PARTITION BY series_id
                               ORDER BY trade_date DESC
                           ) AS row_number
                    FROM experiment_series_daily
                    WHERE run_id = ?
                    {series_filter}
                )
                SELECT series_id, series_name, trade_date, nav, adjust_policy
                FROM ranked
                WHERE row_number <= ?
                ORDER BY series_id, trade_date
                """,
                parameters,
            ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            series_id = str(row["series_id"])
            item = grouped.setdefault(
                series_id,
                {
                    "series_id": series_id,
                    "name": str(row["series_name"]),
                    "adjust_policy": str(row["adjust_policy"]),
                    "as_of": str(run["data_as_of"]),
                    "points": [],
                },
            )
            item["points"].append(
                {
                    "trade_date": str(row["trade_date"]),
                    "nav": float(row["nav"]),
                }
            )
        return [grouped[key] for key in sorted(grouped)]

    def list_experiments(self) -> list[dict[str, Any]]:
        """按最近运行时间返回通用实验摘要。"""
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT
                    e.*,
                    r.run_id AS latest_run_id,
                    r.run_date AS latest_run_date,
                    r.status AS latest_run_status,
                    r.metrics_json AS latest_metrics_json,
                    r.message AS latest_message,
                    r.data_as_of AS latest_data_as_of,
                    r.outcome AS latest_outcome,
                    r.decision_reason AS latest_decision_reason,
                    r.definition_fingerprint AS latest_definition_fingerprint,
                    r.run_fingerprint AS latest_run_fingerprint,
                    r.reuse_count AS latest_reuse_count
                FROM experiments e
                LEFT JOIN experiment_runs r ON r.run_id = (
                    SELECT er.run_id
                    FROM experiment_runs er
                    WHERE er.experiment_id = e.experiment_id
                    ORDER BY er.run_date DESC, er.created_at DESC
                    LIMIT 1
                )
                ORDER BY COALESCE(r.run_date, '') DESC, e.modified_at DESC, e.experiment_id
                """
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = self._row_to_dict(row)
            item["latest_metrics"] = json.loads(item.pop("latest_metrics_json") or "{}")
            result.append(item)
        return result

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
