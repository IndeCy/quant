"""发布基线和运行数据备份。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess
import tarfile
from typing import Any

from runtime.backup import BACKUP_DIR_NAMES, build_backup_manifest
from runtime.paths import RuntimePaths, get_runtime_paths


def create_release_baseline(
    paths: RuntimePaths | None = None,
    output_dir: str | Path | None = None,
    label: str = "release",
) -> dict[str, Any]:
    """创建可迁移的 runtime 备份包、发布 manifest 和恢复说明。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    target_dir = Path(output_dir) if output_dir is not None else runtime_paths.root / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = _safe_label(label)
    archive_path = target_dir / f"quant_runtime_{safe_label}_{stamp}.tar.gz"
    manifest_path = target_dir / f"quant_release_{safe_label}_{stamp}.json"
    guide_path = target_dir / f"RESTORE_{safe_label}_{stamp}.md"

    _write_archive(runtime_paths, archive_path)
    manifest = _build_manifest(runtime_paths, archive_path, manifest_path, guide_path, safe_label)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    guide_path.write_text(_restore_guide(manifest), encoding="utf-8")
    return manifest


def _write_archive(paths: RuntimePaths, archive_path: Path) -> None:
    """把标准 runtime 目录打成 tar.gz。"""
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in BACKUP_DIR_NAMES:
            path = paths.root / name
            if path.exists():
                archive.add(path, arcname=f"runtime/{name}")


def _build_manifest(
    paths: RuntimePaths,
    archive_path: Path,
    manifest_path: Path,
    guide_path: Path,
    label: str,
) -> dict[str, Any]:
    """生成不包含密钥值的发布元数据。"""
    git_state = _git_state(Path(__file__).resolve().parents[1])
    return {
        "label": label,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_root": str(paths.root),
        "archive_path": str(archive_path),
        "manifest_path": str(manifest_path),
        "restore_guide_path": str(guide_path),
        "included_dirs": list(BACKUP_DIR_NAMES),
        "backup_manifest": build_backup_manifest(paths),
        "git_branch": git_state["branch"],
        "git_head": git_state["head"],
        "git_dirty": git_state["dirty"],
        "restore_steps": [
            "在目标机器拉取同一代码分支",
            "解压备份包到新的 QUANT_HOME 父目录",
            "设置 QUANT_HOME 指向解压后的 runtime 目录",
            "安装 Python/Node 依赖并配置 TUSHARE_TOKEN 与 Bark URL",
            "执行 pytest、npm test、npm run build:pre 后启动服务",
        ],
    }


def _git_state(repo_root: Path) -> dict[str, Any]:
    """读取当前 git 分支、HEAD 和 dirty 状态。"""
    branch = _git_output(repo_root, ["git", "branch", "--show-current"])
    head = _git_output(repo_root, ["git", "rev-parse", "--short", "HEAD"])
    status = _git_output(repo_root, ["git", "status", "--porcelain"])
    return {"branch": branch, "head": head, "dirty": bool(status.strip())}


def _git_output(cwd: Path, command: list[str]) -> str:
    try:
        return subprocess.check_output(command, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _restore_guide(manifest: dict[str, Any]) -> str:
    """生成给迁移 Mac mini 时使用的恢复说明。"""
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(manifest["restore_steps"], start=1))
    return "\n".join(
        [
            "# Quant Runtime Restore Guide",
            "",
            f"- Label: {manifest['label']}",
            f"- Archive: {manifest['archive_path']}",
            f"- Git: {manifest['git_branch']} {manifest['git_head']}",
            f"- Dirty worktree when archived: {manifest['git_dirty']}",
            "",
            "## Steps",
            "",
            steps,
            "",
        ]
    )


def _safe_label(label: str) -> str:
    value = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in label.strip())
    return value or "release"
