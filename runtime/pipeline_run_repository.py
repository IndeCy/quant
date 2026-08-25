"""Pipeline 运行记录仓库。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

from runtime.pipeline_context import PipelineContext
from runtime.schema_version import apply_schema_migrations


class PipelineRunRepository:
    """在系统状态库中保存跨入口统一运行记录。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        apply_schema_migrations(self.path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def start(self, context: PipelineContext) -> None:
        """登记开始状态。"""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO pipeline_runs(
                    run_id, pipeline_id, trade_date, trigger_type, status,
                    code_version, data_version, started_at
                ) VALUES (?, ?, ?, ?, 'RUNNING', ?, ?, ?)
                """,
                [
                    context.run_id,
                    context.pipeline_id,
                    context.trade_date,
                    context.trigger_type,
                    context.code_version,
                    context.data_version,
                    context.started_at,
                ],
            )

    def finish(self, run_id: str, status: str, message: str = "") -> None:
        """登记终态和错误摘要。"""
        with self._connect() as con:
            con.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, finished_at = ?, message = ?
                WHERE run_id = ?
                """,
                [status, datetime.now().isoformat(timespec="seconds"), message, run_id],
            )

    def latest(self, pipeline_id: str, trade_date: str) -> dict[str, object] | None:
        """读取指定 Pipeline 交易日最近一次运行。"""
        with self._connect() as con:
            row = con.execute(
                """
                SELECT * FROM pipeline_runs
                WHERE pipeline_id = ? AND trade_date = ?
                ORDER BY started_at DESC, rowid DESC
                LIMIT 1
                """,
                [pipeline_id, trade_date],
            ).fetchone()
        return dict(row) if row else None

    def latest_success(self, pipeline_id: str, trade_date: str) -> dict[str, object] | None:
        """读取已成功运行，用于默认幂等判断。"""
        with self._connect() as con:
            row = con.execute(
                """
                SELECT * FROM pipeline_runs
                WHERE pipeline_id = ? AND trade_date = ? AND status = 'SUCCESS'
                ORDER BY started_at DESC, rowid DESC
                LIMIT 1
                """,
                [pipeline_id, trade_date],
            ).fetchone()
        return dict(row) if row else None
