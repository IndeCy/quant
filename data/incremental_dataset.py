"""契约驱动的 DuckDB 分区增量写入。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

import duckdb
import pandas as pd

from data.dataset_contract import DatasetBinding


class PartitionClient(Protocol):
    """外部数据客户端只需返回一个完整分区。"""

    def fetch_partition(self, partition: str) -> pd.DataFrame: ...


class PartitionSyncState(Protocol):
    """增量更新依赖的最小状态接口，由运行层实现。"""

    def completed_row_count(self, dataset_id: str, partition: str) -> int | None: ...

    def mark_running(self, dataset_id: str, partition: str) -> None: ...

    def mark_success(
        self,
        dataset_id: str,
        partition: str,
        row_count: int,
        content_hash: str,
    ) -> None: ...

    def mark_failure(self, dataset_id: str, partition: str, message: str) -> None: ...


@dataclass(frozen=True)
class DatasetIncrementalResult:
    """一次分区增量更新摘要。"""

    dataset_id: str
    requested_partitions: tuple[str, ...]
    updated_partitions: tuple[str, ...]
    skipped_partitions: tuple[str, ...]
    fetched_rows: int
    stored_rows: int


class ExistingDuckDBIncrementalStore:
    """只写已经由 migration 建好的表，不在运行时创建或修改 Schema。"""

    def __init__(self, binding: DatasetBinding) -> None:
        self.binding = binding
        self.contract = binding.contract
        if not self.contract.date_field:
            raise ValueError("增量数据集必须声明 date_field")
        if not self.contract.write_columns:
            raise ValueError("增量数据集必须声明 write_columns")
        if not binding.path.exists():
            raise FileNotFoundError(f"增量数据库尚未通过 migration 创建: {binding.path}")
        self._validate_schema()

    def replace_partition(self, partition: str, frame: pd.DataFrame) -> int:
        """事务化替换一个完整分区，支持源端订正和删除记录。"""
        clean = self._normalize_partition(partition, frame)
        table = self.contract.table_name
        date_field = self.contract.date_field
        columns = list(self.contract.write_columns)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        con = duckdb.connect(str(self.binding.path))
        try:
            con.execute("BEGIN TRANSACTION")
            con.register("partition_input", clean)
            con.execute(f'DELETE FROM "{table}" WHERE "{date_field}" = ?', [partition])
            if not clean.empty:
                con.execute(
                    f'INSERT INTO "{table}" ({quoted_columns}) '
                    f'SELECT {quoted_columns} FROM partition_input'
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        return self.partition_row_count(partition)

    def partition_row_count(self, partition: str) -> int:
        """读取单分区当前行数。"""
        with duckdb.connect(str(self.binding.path), read_only=True) as con:
            value = con.execute(
                f'SELECT COUNT(*) FROM "{self.contract.table_name}" '
                f'WHERE "{self.contract.date_field}" = ?',
                [partition],
            ).fetchone()[0]
        return int(value)

    def _validate_schema(self) -> None:
        with duckdb.connect(str(self.binding.path), read_only=True) as con:
            tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
            if self.contract.table_name not in tables:
                raise ValueError(f"增量数据库缺少 migration 表: {self.contract.table_name}")
            columns = {
                str(row[0])
                for row in con.execute(f'DESCRIBE "{self.contract.table_name}"').fetchall()
            }
        missing = [column for column in self.contract.write_columns if column not in columns]
        if missing:
            raise ValueError(f"增量表缺少契约字段: {missing}")

    def _normalize_partition(self, partition: str, frame: pd.DataFrame) -> pd.DataFrame:
        columns = list(self.contract.write_columns)
        if frame.empty:
            return pd.DataFrame(columns=columns)
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(f"数据集 {self.contract.dataset_id} 缺少字段: {missing}")
        clean = frame[columns].copy()
        date_field = str(self.contract.date_field)
        clean[date_field] = clean[date_field].fillna("").astype(str).str.replace("-", "", regex=False)
        unexpected = sorted(set(clean[date_field]) - {partition})
        if unexpected:
            raise ValueError(f"分区 {partition} 混入其他日期: {unexpected[:5]}")
        for key in self.contract.primary_key:
            if clean[key].isna().any():
                raise ValueError(f"主键字段 {key} 不能为空")
        duplicates = clean.duplicated(list(self.contract.primary_key), keep=False)
        if duplicates.any():
            raise ValueError(f"数据集 {self.contract.dataset_id} 存在重复主键")
        return clean.sort_values(list(self.contract.primary_key)).reset_index(drop=True)


class IncrementalDatasetUpdater:
    """按完整分区增量同步，失败时保留可恢复状态。"""

    def __init__(
        self,
        client: PartitionClient,
        store: ExistingDuckDBIncrementalStore,
        state: PartitionSyncState | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.state = state

    def update(self, partitions: list[str] | tuple[str, ...]) -> DatasetIncrementalResult:
        requested = tuple(sorted({_normalize_partition(value) for value in partitions}))
        updated: list[str] = []
        skipped: list[str] = []
        fetched_rows = 0
        stored_rows = 0
        dataset_id = self.store.contract.dataset_id
        for partition in requested:
            expected = self.state.completed_row_count(dataset_id, partition) if self.state else None
            if expected is not None and self.store.partition_row_count(partition) == expected:
                skipped.append(partition)
                continue
            if self.state:
                self.state.mark_running(dataset_id, partition)
            try:
                frame = self.client.fetch_partition(partition)
                if frame.empty and not self.store.contract.allow_empty_partition:
                    raise RuntimeError(f"{dataset_id} {partition} 返回空分区，拒绝覆盖")
                fetched_rows += len(frame)
                content_hash = frame_content_hash(frame, self.store.contract.write_columns)
                row_count = self.store.replace_partition(partition, frame)
                stored_rows += row_count
                updated.append(partition)
                if self.state:
                    self.state.mark_success(dataset_id, partition, row_count, content_hash)
            except Exception as exc:
                if self.state:
                    self.state.mark_failure(dataset_id, partition, str(exc))
                raise
        return DatasetIncrementalResult(
            dataset_id=dataset_id,
            requested_partitions=requested,
            updated_partitions=tuple(updated),
            skipped_partitions=tuple(skipped),
            fetched_rows=fetched_rows,
            stored_rows=stored_rows,
        )


def frame_content_hash(frame: pd.DataFrame, columns: tuple[str, ...]) -> str:
    """生成与行顺序无关的轻量内容哈希，供同步审计。"""
    if frame.empty:
        return sha256(b"empty").hexdigest()
    available = [column for column in columns if column in frame.columns]
    ordered = frame[available].copy().sort_values(available).reset_index(drop=True)
    hashed = pd.util.hash_pandas_object(ordered, index=False).values.tobytes()
    return sha256(hashed).hexdigest()


def _normalize_partition(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("分区必须是 YYYYMMDD")
    return normalized
