#!/usr/bin/env python3
"""阻止运行数据库、密钥和每日生成产物进入 Git。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Iterable


DATABASE_SUFFIXES = (".duckdb", ".duckdb.wal", ".db", ".sqlite", ".sqlite3", ".parquet", ".feather")
SECRET_NAMES = {".env", ".env.properties"}
SOURCE_PREFIXES = ("api/", "backtest/", "data/", "domain/", "monitoring/", "runtime/", "scripts/", "strategies/", "frontend/src/")
SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".css")


def _matches_generated(path: str, prefixes: Iterable[str]) -> bool:
    for prefix in prefixes:
        normalized = prefix.rstrip("/")
        if path == normalized or path.startswith(f"{normalized}/"):
            return True
    return False


def find_forbidden_paths(paths: Iterable[str], generated_prefixes: Iterable[str]) -> list[str]:
    """检查给定 Git 路径列表，返回全部违规项。"""
    errors: list[str] = []
    for path in sorted(set(paths)):
        name = Path(path).name
        if path.endswith(DATABASE_SUFFIXES):
            errors.append(f"{path}: 运行数据库不得提交")
        elif name in SECRET_NAMES or name.startswith(".env.") and name != ".env.properties.example":
            errors.append(f"{path}: 环境密钥文件不得提交")
        elif _matches_generated(path, generated_prefixes):
            errors.append(f"{path}: 自动生成产物不得提交")
    return errors


def tracked_files(root: Path) -> list[str]:
    """读取 Git 索引和未忽略的新文件；提交前即可发现违规产物。"""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def find_ignored_sources(paths: Iterable[str]) -> list[str]:
    """源码目录中的文件不得被宽泛 `.gitignore` 规则静默吞掉。"""
    return sorted(
        path
        for path in set(paths)
        if path.startswith(SOURCE_PREFIXES) and path.endswith(SOURCE_SUFFIXES)
    )


def ignored_files(root: Path) -> list[str]:
    """读取被 Git 忽略的未跟踪文件。"""
    result = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    rules = json.loads((root / "config" / "architecture_rules.json").read_text(encoding="utf-8"))
    errors = find_forbidden_paths(tracked_files(root), rules.get("generated_paths", []))
    errors.extend(f"{path}: 源码文件被 .gitignore 忽略" for path in find_ignored_sources(ignored_files(root)))
    if errors:
        print("Git产物围栏检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Git产物围栏检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
