"""在现有 Pipeline 数据更新节点内复用的增量同步服务。"""

from __future__ import annotations

from data.incremental_dataset import DatasetIncrementalResult, IncrementalDatasetUpdater
from runtime.data_sync_repository import DataSyncRepository


class DataSyncService:
    """统一同步审计；本类本身不是第二个 Pipeline 入口。"""

    def __init__(self, repository: DataSyncRepository) -> None:
        self.repository = repository

    def sync(
        self,
        updater: IncrementalDatasetUpdater,
        partitions: list[str] | tuple[str, ...],
        *,
        trigger_source: str,
    ) -> tuple[str, DatasetIncrementalResult]:
        """执行一次分区同步并记录运行与失败状态。"""
        if not partitions:
            raise ValueError("partitions 不能为空")
        normalized = sorted({str(value).replace("-", "") for value in partitions})
        dataset_id = updater.store.contract.dataset_id
        sync_id = self.repository.start_run(
            dataset_id,
            normalized[0],
            normalized[-1],
            trigger_source,
        )
        updater.state = self.repository.for_run(sync_id)
        try:
            result = updater.update(tuple(normalized))
            self.repository.finish_run(
                sync_id,
                "SUCCESS",
                fetched_rows=result.fetched_rows,
                stored_rows=result.stored_rows,
            )
            return sync_id, result
        except Exception as exc:
            self.repository.finish_run(sync_id, "FAILED", message=str(exc))
            raise
