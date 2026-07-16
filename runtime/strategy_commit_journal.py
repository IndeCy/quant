"""策略跨存储提交的幂等日志与恢复状态。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3

from runtime.schema_version import apply_schema_migrations


COMMIT_STEPS = (
    "BEGIN",
    "ADAPTER_PERSISTED",
    "PAPER_SYNCED",
    "RUN_RECORDED",
    "NOTIFICATION_DISPATCHING",
    "COMPLETED",
)
STEP_RANK = {step: index for index, step in enumerate(COMMIT_STEPS)}


@dataclass(frozen=True)
class CommitLease:
    """一次提交尝试取得的逻辑提交租约。"""

    commit_id: str
    strategy_id: str
    trade_date: str
    last_step: str
    attempt_count: int
    resumed: bool
    skip: bool


class StrategyCommitJournalRepository:
    """保存每个策略交易日的最后成功提交检查点。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        apply_schema_migrations(self.path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def begin(
        self,
        strategy_id: str,
        trade_date: str,
        pipeline_run_id: str,
        code_version: str = "",
        data_version: str = "",
        *,
        force: bool = False,
    ) -> CommitLease:
        """开始、接管或跳过一个逻辑提交。"""
        commit_id = _commit_id(strategy_id, trade_date)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT * FROM strategy_commit_journal WHERE commit_id = ?",
                [commit_id],
            ).fetchone()
            if row is None:
                con.execute(
                    """
                    INSERT INTO strategy_commit_journal(
                        commit_id, strategy_id, trade_date, pipeline_run_id, status,
                        last_step, attempt_count, code_version, data_version
                    ) VALUES (?, ?, ?, ?, 'COMMITTING', 'BEGIN', 1, ?, ?)
                    """,
                    [commit_id, strategy_id, trade_date, pipeline_run_id, code_version, data_version],
                )
                return CommitLease(commit_id, strategy_id, trade_date, "BEGIN", 1, False, False)

            if str(row["status"]) == "COMPLETED" and not force:
                return CommitLease(
                    commit_id,
                    strategy_id,
                    trade_date,
                    "COMPLETED",
                    int(row["attempt_count"]),
                    False,
                    True,
                )

            versions_changed = (
                str(row["code_version"]) != code_version
                or str(row["data_version"]) != data_version
            )
            reset = force or versions_changed
            last_step = "BEGIN" if reset else str(row["last_step"])
            attempts = int(row["attempt_count"]) + 1
            con.execute(
                """
                UPDATE strategy_commit_journal
                SET pipeline_run_id = ?, status = 'COMMITTING', last_step = ?,
                    attempt_count = ?, code_version = ?, data_version = ?,
                    error_message = '', updated_at = CURRENT_TIMESTAMP, completed_at = ''
                WHERE commit_id = ?
                """,
                [pipeline_run_id, last_step, attempts, code_version, data_version, commit_id],
            )
        return CommitLease(
            commit_id,
            strategy_id,
            trade_date,
            last_step,
            attempts,
            resumed=not reset,
            skip=False,
        )

    def checkpoint(self, commit_id: str, step: str) -> None:
        """推进最后成功检查点，不允许无意回退。"""
        _validate_step(step)
        with self._connect() as con:
            row = con.execute(
                "SELECT last_step FROM strategy_commit_journal WHERE commit_id = ?",
                [commit_id],
            ).fetchone()
            if row is None:
                raise KeyError(commit_id)
            current = str(row["last_step"])
            _validate_step(current)
            if STEP_RANK[step] < STEP_RANK[current]:
                raise ValueError(f"commit checkpoint cannot move backwards: {current} -> {step}")
            con.execute(
                """
                UPDATE strategy_commit_journal
                SET status = 'COMMITTING', last_step = ?, error_message = '',
                    updated_at = CURRENT_TIMESTAMP
                WHERE commit_id = ?
                """,
                [step, commit_id],
            )

    def fail(self, commit_id: str, message: str) -> None:
        """保留最后成功检查点并登记本次失败。"""
        with self._connect() as con:
            cursor = con.execute(
                """
                UPDATE strategy_commit_journal
                SET status = 'FAILED', error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE commit_id = ?
                """,
                [message[-2000:], commit_id],
            )
            if cursor.rowcount == 0:
                raise KeyError(commit_id)

    def complete(self, commit_id: str) -> None:
        """把提交标记为完成。"""
        completed_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            cursor = con.execute(
                """
                UPDATE strategy_commit_journal
                SET status = 'COMPLETED', last_step = 'COMPLETED', error_message = '',
                    updated_at = CURRENT_TIMESTAMP, completed_at = ?
                WHERE commit_id = ?
                """,
                [completed_at, commit_id],
            )
            if cursor.rowcount == 0:
                raise KeyError(commit_id)

    def get(self, strategy_id: str, trade_date: str) -> dict[str, object] | None:
        """读取一个策略交易日的提交状态。"""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM strategy_commit_journal WHERE commit_id = ?",
                [_commit_id(strategy_id, trade_date)],
            ).fetchone()
        return dict(row) if row else None

    def list_incomplete(self) -> list[dict[str, object]]:
        """列出需要后续标准 Pipeline 恢复的提交。"""
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM strategy_commit_journal
                WHERE status IN ('COMMITTING', 'FAILED')
                ORDER BY trade_date, strategy_id
                """
            ).fetchall()
        return [dict(row) for row in rows]


def step_completed(last_step: str, required_step: str) -> bool:
    """判断恢复租约是否已越过某检查点。"""
    _validate_step(last_step)
    _validate_step(required_step)
    return STEP_RANK[last_step] >= STEP_RANK[required_step]


def _commit_id(strategy_id: str, trade_date: str) -> str:
    if not strategy_id.strip() or len(trade_date) != 8 or not trade_date.isdigit():
        raise ValueError("strategy commit requires strategy_id and YYYYMMDD trade_date")
    return f"{strategy_id}:{trade_date}"


def _validate_step(step: str) -> None:
    if step not in STEP_RANK:
        raise ValueError(f"unsupported strategy commit step: {step}")

