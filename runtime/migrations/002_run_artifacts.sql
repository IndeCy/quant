CREATE TABLE run_artifacts (
    artifact_id TEXT NOT NULL PRIMARY KEY,
    run_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX uk_run_artifacts_path
ON run_artifacts(run_id, file_path);

CREATE INDEX idx_run_artifacts_run
ON run_artifacts(run_id, artifact_type);
