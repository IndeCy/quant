"""运行目录备份清单。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

from runtime.config import default_config_path
from runtime.paths import RuntimePaths, get_runtime_paths


BACKUP_DIR_NAMES = ["data", "state", "runs", "reports", "config", "logs"]


def build_backup_manifest(paths: RuntimePaths | None = None) -> dict[str, Any]:
    """生成迁移和备份所需的只读清单。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    items = [_describe_path(runtime_paths.root / name, name) for name in BACKUP_DIR_NAMES]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    includes = " ".join(BACKUP_DIR_NAMES)
    return {
        "runtime_root": str(runtime_paths.root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "external_items": [
            _describe_external(default_config_path(), "local_config", "含密钥，需加密或点对点迁移"),
            _describe_external(runtime_paths.base_market_path, "base_market", "只读大文件，可单独复制或挂载"),
        ],
        "backup_command": f"tar -czf quant_runtime_backup_{stamp}.tar.gz -C {runtime_paths.root} {includes}",
        "restore_check_command": (
            f"{sys.executable} scripts/verify_runtime_restore.py --runtime-root {runtime_paths.root}"
        ),
    }


def _describe_path(path: Path, name: str) -> dict[str, Any]:
    """统计路径存在性、文件数量和字节大小。"""
    files = [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
    size_bytes = sum(item.stat().st_size for item in files)
    return {
        "name": name,
        "path": str(path),
        "exists": path.exists(),
        "file_count": len(files),
        "size_bytes": size_bytes,
    }


def _describe_external(path: Path, name: str, note: str) -> dict[str, Any]:
    """描述不进入普通运行目录压缩包、但迁移时必须处理的文件。"""
    return {
        "name": name,
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "note": note,
    }
