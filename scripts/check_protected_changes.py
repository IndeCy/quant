#!/usr/bin/env python3
"""检测 M0 和数据库 Schema 等受保护变更。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Iterable


def changed_files(root: Path, base_ref: str) -> list[str]:
    """读取相对基准的已提交和工作区变化。"""
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(set(line for line in result.stdout.splitlines() if line))


def find_protected_changes(changed: Iterable[str], protected: Iterable[str]) -> list[str]:
    """返回发生变化的 M0 文件。"""
    protected_set = set(protected)
    return sorted(path for path in set(changed) if path in protected_set)


def schema_change_without_migration(changed: Iterable[str]) -> bool:
    """初始化 Schema 变化必须伴随新的 migration。"""
    paths = set(changed)
    schema_changed = "runtime/repository_schema.py" in paths
    migration_added = any(path.startswith("runtime/migrations/") and path.endswith(".sql") for path in paths)
    return schema_changed and not migration_added


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--base-ref", default=os.environ.get("GUARDRAIL_BASE_REF", "HEAD"))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    rules = json.loads((root / "config" / "architecture_rules.json").read_text(encoding="utf-8"))
    changed = changed_files(root, args.base_ref)
    protected = find_protected_changes(changed, rules.get("protected_m0_paths", []))
    errors: list[str] = []
    if protected and os.environ.get("QUANT_APPROVE_M0_CHANGE") != "1":
        errors.append("M0受保护文件发生变化，需用户确认并设置 QUANT_APPROVE_M0_CHANGE=1")
        errors.extend(f"受保护文件: {path}" for path in protected)
    if schema_change_without_migration(changed):
        errors.append("runtime/repository_schema.py 已变化，但没有新增 runtime/migrations/*.sql")
    if errors:
        print("受保护变更检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("受保护变更检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
