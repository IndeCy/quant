CREATE TABLE IF NOT EXISTS data_sync_runs (
    sync_id TEXT NOT NULL PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    start_partition TEXT NOT NULL,
    end_partition TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched_rows INTEGER NOT NULL DEFAULT 0,
    stored_rows INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_sync_partitions (
    dataset_id TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    status TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    last_sync_id TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    completed_at TEXT,
    modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dataset_id, partition_key)
);

CREATE INDEX IF NOT EXISTS idx_data_sync_runs_dataset
ON data_sync_runs(dataset_id, started_at);

CREATE INDEX IF NOT EXISTS idx_data_sync_partitions_status
ON data_sync_partitions(status, dataset_id, partition_key);
