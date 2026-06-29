"""运行日志索引与读取。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from runtime.paths import RuntimePaths, get_runtime_paths


def list_log_files(paths: RuntimePaths | None = None) -> list[dict[str, Any]]:
    """列出服务日志和每日流水线 run_log。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    items: list[dict[str, Any]] = []
    for path in sorted(runtime_paths.runs_dir.glob("*/run_log.txt"), reverse=True):
        items.append(_describe_log(runtime_paths, path, "run", f"{path.parent.name}/run_log.txt"))
    for path in sorted(runtime_paths.logs_dir.glob("*.log")):
        items.append(_describe_log(runtime_paths, path, "service", path.name))
    return items


def read_log_file(paths: RuntimePaths | None, log_id: str) -> dict[str, Any] | None:
    """按日志ID读取内容，只允许读取索引内日志。"""
    runtime_paths = paths or get_runtime_paths()
    indexed = {item["log_id"]: item for item in list_log_files(runtime_paths)}
    item = indexed.get(log_id)
    if item is None:
        return None
    path = Path(str(item["path"]))
    content = path.read_text(encoding="utf-8", errors="replace")
    return {**item, "content": content}


def _describe_log(paths: RuntimePaths, path: Path, log_type: str, name: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "log_id": _encode_log_id(path),
        "log_type": log_type,
        "name": name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime,
        "runtime_root": str(paths.root),
    }


def _encode_log_id(path: Path) -> str:
    return base64.urlsafe_b64encode(str(path.resolve()).encode("utf-8")).decode("ascii").rstrip("=")
