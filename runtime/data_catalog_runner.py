"""Data Catalog 刷新任务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.data_catalog import discover_data_sources
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


def refresh_data_catalog(
    paths: RuntimePaths | None = None,
    roots: list[str | Path] | None = None,
) -> dict[str, Any]:
    """扫描本地数据文件并写入系统状态库。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    scan_roots = roots or _default_scan_roots(runtime_paths)
    repository = SystemRepository(runtime_paths.system_state_path)
    sources = discover_data_sources(scan_roots)
    for source in sources:
        repository.upsert_data_source(source)
    return {
        "status": "SUCCESS",
        "source_count": len(sources),
        "ok_count": sum(1 for item in sources if item["status"] == "OK"),
        "error_count": sum(1 for item in sources if item["status"] == "ERROR"),
        "sources": sources,
    }


def _default_scan_roots(paths: RuntimePaths) -> list[Path]:
    """默认只扫描关键数据资产位置，避免递归扫完整工程。"""
    root_files = [
        path
        for path in paths.root.iterdir()
        if path.is_file() and path.suffix in {".duckdb", ".sqlite", ".sqlite3"}
    ]
    return [*root_files, paths.data_dir]
