"""系统运行状态 SQLite 仓库。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from runtime.repository_schema import init_system_schema


class SystemRepository:
    """保存每日运行状态和报告索引，供后续前端统一读取。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            self._init_schema(con)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def record_strategy_run(
        self,
        strategy_id: str,
        trade_date: str,
        status: str,
        run_dir: str | Path,
        message: str = "",
    ) -> None:
        """按策略和日期幂等记录一次生产流水线运行。"""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO strategy_runs(
                    strategy_id, trade_date, status, run_dir, message
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id, trade_date) DO UPDATE SET
                    status=excluded.status,
                    run_dir=excluded.run_dir,
                    message=excluded.message,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [strategy_id, trade_date, status, str(run_dir), message],
            )

    def upsert_factor(
        self,
        factor_id: str,
        name: str,
        category: str,
        direction: str,
        source: str,
        description: str = "",
        enabled: bool = True,
        config: dict[str, Any] | None = None,
    ) -> None:
        """登记可组合因子元数据，暂不计算因子值。"""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO factor_registry(
                    factor_id, name, category, direction, source,
                    description, enabled, config_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(factor_id) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    direction=excluded.direction,
                    source=excluded.source,
                    description=excluded.description,
                    enabled=excluded.enabled,
                    config_json=excluded.config_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    factor_id,
                    name,
                    category,
                    direction,
                    source,
                    description,
                    1 if enabled else 0,
                    json.dumps(config or {}, ensure_ascii=False, sort_keys=True),
                ],
            )

    def upsert_strategy(
        self,
        strategy_id: str,
        name: str,
        status: str,
        strategy_type: str,
        description: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        """登记策略元数据，供前端维护和运行中心展示。"""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO strategy_registry(
                    strategy_id, name, status, strategy_type, description, config_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    strategy_type=excluded.strategy_type,
                    description=excluded.description,
                    config_json=excluded.config_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    strategy_id,
                    name,
                    status,
                    strategy_type,
                    description,
                    json.dumps(config or {}, ensure_ascii=False, sort_keys=True),
                ],
            )

    def replace_strategy_factors(self, strategy_id: str, factors: Iterable[dict[str, Any]]) -> None:
        """替换某策略的因子组合关系。"""
        rows = list(factors)
        with self._connect() as con:
            con.execute("DELETE FROM strategy_factor_link WHERE strategy_id = ?", [strategy_id])
            con.executemany(
                """
                INSERT INTO strategy_factor_link(
                    strategy_id, factor_id, weight, transform, enabled
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        strategy_id,
                        str(item["factor_id"]),
                        float(item.get("weight", 1.0)),
                        str(item.get("transform", "zscore")),
                        1 if bool(item.get("enabled", True)) else 0,
                    )
                    for item in rows
                ],
            )

    def load_strategy_definition(self, strategy_id: str) -> dict[str, Any] | None:
        """读取策略及其因子组合定义。"""
        with self._connect() as con:
            strategy = con.execute(
                "SELECT * FROM strategy_registry WHERE strategy_id = ?",
                [strategy_id],
            ).fetchone()
            if strategy is None:
                return None
            factors = con.execute(
                """
                SELECT l.factor_id, f.name, f.category, f.direction, l.weight, l.transform, l.enabled
                FROM strategy_factor_link l
                LEFT JOIN factor_registry f ON l.factor_id = f.factor_id
                WHERE l.strategy_id = ?
                ORDER BY l.factor_id
                """,
                [strategy_id],
            ).fetchall()
        result = self._row_to_dict(strategy)
        result["factors"] = [self._row_to_dict(row) for row in factors]
        return result

    def list_strategies(self) -> list[dict[str, Any]]:
        """读取全部策略定义，按策略ID排序。"""
        with self._connect() as con:
            rows = con.execute("SELECT * FROM strategy_registry ORDER BY strategy_id").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_factors(self) -> list[dict[str, Any]]:
        """读取全部因子定义，按因子ID排序。"""
        with self._connect() as con:
            rows = con.execute("SELECT * FROM factor_registry ORDER BY factor_id").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def load_factor_definition(self, factor_id: str) -> dict[str, Any] | None:
        """读取因子定义及使用该因子的策略关系。"""
        with self._connect() as con:
            factor = con.execute(
                "SELECT * FROM factor_registry WHERE factor_id = ?",
                [factor_id],
            ).fetchone()
            if factor is None:
                return None
            strategies = con.execute(
                """
                SELECT
                    s.strategy_id,
                    s.name,
                    s.status,
                    l.weight,
                    l.transform,
                    l.enabled
                FROM strategy_factor_link l
                JOIN strategy_registry s ON l.strategy_id = s.strategy_id
                WHERE l.factor_id = ?
                ORDER BY s.strategy_id
                """,
                [factor_id],
            ).fetchall()
        result = self._row_to_dict(factor)
        result["strategies"] = [self._row_to_dict(row) for row in strategies]
        return result

    def upsert_strategy_draft(
        self,
        draft_id: str,
        name: str,
        description: str = "",
        config: dict[str, Any] | None = None,
        factors: Iterable[dict[str, Any]] = (),
    ) -> None:
        """保存本地策略草案和因子组合，不影响生产策略。"""
        rows = list(factors)
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO strategy_drafts(
                    draft_id, name, status, description, config_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    description=excluded.description,
                    config_json=excluded.config_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    draft_id,
                    name,
                    "draft",
                    description,
                    json.dumps(config or {}, ensure_ascii=False, sort_keys=True),
                ],
            )
            con.execute("DELETE FROM strategy_draft_factors WHERE draft_id = ?", [draft_id])
            con.executemany(
                """
                INSERT INTO strategy_draft_factors(
                    draft_id, factor_id, weight, transform, enabled
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        draft_id,
                        str(item["factor_id"]),
                        float(item.get("weight", 1.0)),
                        str(item.get("transform", "winsorize_zscore")),
                        1 if bool(item.get("enabled", True)) else 0,
                    )
                    for item in rows
                ],
            )

    def load_strategy_draft(self, draft_id: str) -> dict[str, Any] | None:
        """读取本地策略草案及其因子组合。"""
        with self._connect() as con:
            draft = con.execute(
                "SELECT * FROM strategy_drafts WHERE draft_id = ?",
                [draft_id],
            ).fetchone()
            if draft is None:
                return None
            factors = con.execute(
                """
                SELECT d.factor_id, f.name, f.category, f.direction, d.weight, d.transform, d.enabled
                FROM strategy_draft_factors d
                LEFT JOIN factor_registry f ON d.factor_id = f.factor_id
                WHERE d.draft_id = ?
                ORDER BY d.factor_id
                """,
                [draft_id],
            ).fetchall()
        result = self._row_to_dict(draft)
        result["factors"] = [self._row_to_dict(row) for row in factors]
        return result

    def list_strategy_drafts(self) -> list[dict[str, Any]]:
        """读取本地策略草案列表。"""
        with self._connect() as con:
            rows = con.execute("SELECT * FROM strategy_drafts ORDER BY modified_at DESC, draft_id").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_runs(self, strategy_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        """按日期倒序读取运行记录。"""
        sql = "SELECT * FROM strategy_runs"
        params: list[Any] = []
        if strategy_id:
            sql += " WHERE strategy_id = ?"
            params.append(strategy_id)
        sql += " ORDER BY trade_date DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_run(self, strategy_id: str, trade_date: str) -> dict[str, Any] | None:
        """读取某策略某日运行记录。"""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM strategy_runs WHERE strategy_id = ? AND trade_date = ?",
                [strategy_id, trade_date],
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def record_run_step(
        self,
        strategy_id: str,
        trade_date: str,
        sequence: int,
        step_name: str,
        status: str,
        message: str = "",
        artifact_path: str | Path = "",
    ) -> None:
        """按策略、日期和步骤名幂等记录 pipeline 步骤状态。"""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO strategy_run_steps(
                    strategy_id, trade_date, sequence, step_name, status, message, artifact_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id, trade_date, step_name) DO UPDATE SET
                    sequence=excluded.sequence,
                    status=excluded.status,
                    message=excluded.message,
                    artifact_path=excluded.artifact_path,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [strategy_id, trade_date, int(sequence), step_name, status, message, str(artifact_path)],
            )

    def list_run_steps(self, strategy_id: str, trade_date: str) -> list[dict[str, Any]]:
        """读取某次运行的 pipeline 步骤。"""
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM strategy_run_steps
                WHERE strategy_id = ? AND trade_date = ?
                ORDER BY sequence, step_name
                """,
                [strategy_id, trade_date],
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_report(
        self,
        report_type: str,
        strategy_id: str,
        trade_date: str,
        title: str,
        file_path: str | Path,
        tags: Iterable[str] = (),
    ) -> None:
        """登记一个报告或运行产物，避免前端直接扫描散落文件。"""
        normalized_path = str(Path(file_path))
        report_id = f"{strategy_id}:{trade_date}:{report_type}:{Path(file_path).name}"
        tags_json = json.dumps(list(tags), ensure_ascii=False)
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO report_index(
                    report_id, report_type, strategy_id, trade_date,
                    title, file_path, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    report_type=excluded.report_type,
                    strategy_id=excluded.strategy_id,
                    trade_date=excluded.trade_date,
                    title=excluded.title,
                    file_path=excluded.file_path,
                    tags_json=excluded.tags_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [report_id, report_type, strategy_id, trade_date, title, normalized_path, tags_json],
            )

    def list_reports(self, strategy_id: str | None = None) -> list[dict[str, Any]]:
        """按日期倒序读取报告索引。"""
        sql = "SELECT * FROM report_index"
        params: list[str] = []
        if strategy_id:
            sql += " WHERE strategy_id = ?"
            params.append(strategy_id)
        sql += " ORDER BY trade_date DESC, report_type ASC"
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """按报告ID读取单条报告索引。"""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM report_index WHERE report_id = ?",
                [report_id],
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def latest_run(self, strategy_id: str) -> dict[str, Any] | None:
        """读取某策略最近一次运行状态。"""
        with self._connect() as con:
            row = con.execute(
                """
                SELECT * FROM strategy_runs
                WHERE strategy_id = ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                [strategy_id],
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def _init_schema(self, con: sqlite3.Connection) -> None:
        init_system_schema(con)

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        if "tags_json" in result:
            result["tags"] = json.loads(result.pop("tags_json") or "[]")
        if "config_json" in result:
            result["config"] = json.loads(result.pop("config_json") or "{}")
        if "enabled" in result:
            result["enabled"] = bool(result["enabled"])
        return result
