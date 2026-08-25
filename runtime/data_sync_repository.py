"""统一数据增量同步状态仓库。"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from uuid import uuid4

from runtime.schema_version import apply_schema_migrations


class DataSyncRepository:
    """记录同步运行和分区检查点，支持失败恢复与幂等跳过。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        apply_schema_migrations(self.path)

    def start_run(
        self,
        dataset_id: str,
        start_partition: str,
        end_partition: str,
        trigger_source: str,
    ) -> str:
        """登记一次同步运行。"""
        sync_id = uuid4().hex
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO data_sync_runs(
                    sync_id, dataset_id, start_partition, end_partition,
                    trigger_source, status
                ) VALUES (?, ?, ?, ?, ?, 'RUNNING')
                """,
                [sync_id, dataset_id, start_partition, end_partition, trigger_source],
            )
        return sync_id

    def finish_run(
        self,
        sync_id: str,
        status: str,
        *,
        fetched_rows: int = 0,
        stored_rows: int = 0,
        message: str = "",
    ) -> None:
        """完成或失败同步运行。"""
        if status not in {"SUCCESS", "FAILED"}:
            raise ValueError(f"不支持的同步状态: {status}")
        with self._connect() as con:
            con.execute(
                """
                UPDATE data_sync_runs
                SET status=?, fetched_rows=?, stored_rows=?, message=?,
                    completed_at=CURRENT_TIMESTAMP, modified_at=CURRENT_TIMESTAMP
                WHERE sync_id=?
                """,
                [status, int(fetched_rows), int(stored_rows), message, sync_id],
            )

    def for_run(self, sync_id: str) -> "DataSyncRunState":
        """创建绑定 run_id 的分区状态适配器。"""
        return DataSyncRunState(self, sync_id)

    def load_run(self, sync_id: str) -> dict[str, object] | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM data_sync_runs WHERE sync_id=?", [sync_id]).fetchone()
        return dict(row) if row else None

    def load_partition(self, dataset_id: str, partition: str) -> dict[str, object] | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM data_sync_partitions WHERE dataset_id=? AND partition_key=?",
                [dataset_id, partition],
            ).fetchone()
        return dict(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con


class DataSyncRunState:
    """实现 data.incremental_dataset.PartitionSyncState。"""

    def __init__(self, repository: DataSyncRepository, sync_id: str) -> None:
        self.repository = repository
        self.sync_id = sync_id

    def completed_row_count(self, dataset_id: str, partition: str) -> int | None:
        row = self.repository.load_partition(dataset_id, partition)
        if row is None or row["status"] != "SUCCESS":
            return None
        return int(row["row_count"])

    def mark_running(self, dataset_id: str, partition: str) -> None:
        with self.repository._connect() as con:
            con.execute(
                """
                INSERT INTO data_sync_partitions(
                    dataset_id, partition_key, status, last_sync_id,
                    started_at, error_message
                ) VALUES (?, ?, 'RUNNING', ?, CURRENT_TIMESTAMP, '')
                ON CONFLICT(dataset_id, partition_key) DO UPDATE SET
                    status='RUNNING', last_sync_id=excluded.last_sync_id,
                    started_at=CURRENT_TIMESTAMP, completed_at=NULL,
                    error_message='', modified_at=CURRENT_TIMESTAMP
                """,
                [dataset_id, partition, self.sync_id],
            )

    def mark_success(
        self,
        dataset_id: str,
        partition: str,
        row_count: int,
        content_hash: str,
    ) -> None:
        with self.repository._connect() as con:
            con.execute(
                """
                UPDATE data_sync_partitions
                SET status='SUCCESS', row_count=?, content_hash=?, error_message='',
                    completed_at=CURRENT_TIMESTAMP, modified_at=CURRENT_TIMESTAMP
                WHERE dataset_id=? AND partition_key=? AND last_sync_id=?
                """,
                [int(row_count), content_hash, dataset_id, partition, self.sync_id],
            )

    def mark_failure(self, dataset_id: str, partition: str, message: str) -> None:
        with self.repository._connect() as con:
            con.execute(
                """
                UPDATE data_sync_partitions
                SET status='FAILED', error_message=?, completed_at=CURRENT_TIMESTAMP,
                    modified_at=CURRENT_TIMESTAMP
                WHERE dataset_id=? AND partition_key=? AND last_sync_id=?
                """,
                [message[:2000], dataset_id, partition, self.sync_id],
            )
