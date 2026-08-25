"""增量同步运行状态与 migration 测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from data.dataset_contract import DatasetBinding, DatasetContract
from data.incremental_dataset import ExistingDuckDBIncrementalStore, IncrementalDatasetUpdater
from runtime.data_sync_repository import DataSyncRepository
from runtime.data_sync_service import DataSyncService
from runtime.schema_version import current_schema_version


class OneRowClient:
    def fetch_partition(self, partition: str) -> pd.DataFrame:
        return pd.DataFrame([{"trade_date": partition, "ts_code": "AAA.SZ", "value": 1.0}])


def test_service_records_run_and_partition_checkpoint(tmp_path: Path) -> None:
    database = tmp_path / "data.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE values_daily(trade_date VARCHAR, ts_code VARCHAR, value DOUBLE, PRIMARY KEY(trade_date, ts_code))")
    contract = DatasetContract(
        "factor.test",
        "values_daily",
        ("trade_date", "ts_code"),
        "trade_date",
        "ts_code",
        write_columns=("trade_date", "ts_code", "value"),
    )
    store = ExistingDuckDBIncrementalStore(DatasetBinding(contract, database))
    updater = IncrementalDatasetUpdater(OneRowClient(), store)
    repository = DataSyncRepository(tmp_path / "state.sqlite")

    sync_id, result = DataSyncService(repository).sync(
        updater,
        ["20240102"],
        trigger_source="test",
    )

    run = repository.load_run(sync_id)
    partition = repository.load_partition("factor.test", "20240102")
    assert result.stored_rows == 1
    assert run is not None and run["status"] == "SUCCESS"
    assert partition is not None and partition["status"] == "SUCCESS"
    assert partition["row_count"] == 1
    assert current_schema_version(tmp_path / "state.sqlite") == 10
