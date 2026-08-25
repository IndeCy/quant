"""契约驱动的分区增量同步测试。"""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.dataset_contract import DatasetBinding, DatasetContract
from data.incremental_dataset import ExistingDuckDBIncrementalStore, IncrementalDatasetUpdater


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_partition(self, partition: str) -> pd.DataFrame:
        self.calls.append(partition)
        return pd.DataFrame(
            [
                {"trade_date": partition, "ts_code": "AAA.SZ", "value": 1.0},
                {"trade_date": partition, "ts_code": "BBB.SZ", "value": 2.0},
            ]
        )


class MemoryState:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], int] = {}
        self.status: dict[tuple[str, str], str] = {}

    def completed_row_count(self, dataset_id: str, partition: str) -> int | None:
        key = (dataset_id, partition)
        return self.rows.get(key) if self.status.get(key) == "SUCCESS" else None

    def mark_running(self, dataset_id: str, partition: str) -> None:
        self.status[(dataset_id, partition)] = "RUNNING"

    def mark_success(self, dataset_id: str, partition: str, row_count: int, content_hash: str) -> None:
        self.status[(dataset_id, partition)] = "SUCCESS"
        self.rows[(dataset_id, partition)] = row_count

    def mark_failure(self, dataset_id: str, partition: str, message: str) -> None:
        self.status[(dataset_id, partition)] = "FAILED"


def test_incremental_updater_replaces_partition_and_skips_verified_checkpoint(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = FakeClient()
    state = MemoryState()
    updater = IncrementalDatasetUpdater(client, store, state)

    first = updater.update(["20240102"])
    second = updater.update(["20240102"])

    assert first.updated_partitions == ("20240102",)
    assert second.skipped_partitions == ("20240102",)
    assert client.calls == ["20240102"]
    assert store.partition_row_count("20240102") == 2


def test_checkpoint_row_mismatch_forces_refetch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = FakeClient()
    state = MemoryState()
    updater = IncrementalDatasetUpdater(client, store, state)
    updater.update(["20240102"])
    with duckdb.connect(str(store.binding.path)) as con:
        con.execute("DELETE FROM values_daily WHERE ts_code='BBB.SZ'")

    result = updater.update(["20240102"])

    assert result.updated_partitions == ("20240102",)
    assert client.calls == ["20240102", "20240102"]
    assert store.partition_row_count("20240102") == 2


def test_store_rejects_cross_partition_and_duplicate_keys(tmp_path: Path) -> None:
    store = _store(tmp_path)
    mixed = pd.DataFrame([{"trade_date":"20240103","ts_code":"AAA.SZ","value":1.0}])
    duplicate = pd.DataFrame(
        [
            {"trade_date":"20240102","ts_code":"AAA.SZ","value":1.0},
            {"trade_date":"20240102","ts_code":"AAA.SZ","value":2.0},
        ]
    )

    with pytest.raises(ValueError, match="混入其他日期"):
        store.replace_partition("20240102", mixed)
    with pytest.raises(ValueError, match="重复主键"):
        store.replace_partition("20240102", duplicate)


def test_store_requires_pre_migrated_database(tmp_path: Path) -> None:
    contract = _contract()
    with pytest.raises(FileNotFoundError, match="migration"):
        ExistingDuckDBIncrementalStore(DatasetBinding(contract, tmp_path / "missing.duckdb"))


def _store(tmp_path: Path) -> ExistingDuckDBIncrementalStore:
    path = tmp_path / "increment.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE values_daily(trade_date VARCHAR, ts_code VARCHAR, value DOUBLE, PRIMARY KEY(trade_date, ts_code))")
    return ExistingDuckDBIncrementalStore(DatasetBinding(_contract(), path))


def _contract() -> DatasetContract:
    return DatasetContract(
        dataset_id="factor.test",
        table_name="values_daily",
        primary_key=("trade_date", "ts_code"),
        date_field="trade_date",
        symbol_field="ts_code",
        write_columns=("trade_date", "ts_code", "value"),
    )
