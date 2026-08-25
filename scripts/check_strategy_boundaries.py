#!/usr/bin/env python3
"""校验策略声明版本和公共模块中的策略特殊分支。"""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.strategy_definition_loader import load_strategy_definitions


GENERIC_RUNTIME_FILES = [
    "runtime/pipeline_service.py",
    "runtime/local_paper_broker.py",
    "runtime/scheduler.py",
]


def compare_strategy_payloads(
    previous: dict[str, Any],
    current: dict[str, Any],
    path: str,
) -> list[str]:
    """策略业务定义变化时要求显式提升版本。"""
    if previous == current:
        return []
    old_version = str(previous.get("version") or "")
    new_version = str(current.get("version") or "")
    if old_version == new_version:
        return [f"{path}: 策略定义已变化，但版本仍为 {new_version}"]
    return []


def _git_json(root: Path, ref: str, relative: str) -> dict[str, Any] | None:
    """读取基准提交中的 JSON；新文件返回 None。"""
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def check_version_bumps(root: Path, base_ref: str) -> list[str]:
    """比较基准提交和当前工作区的全部策略声明。"""
    errors: list[str] = []
    for path in sorted((root / "config" / "strategies").glob("*.json")):
        relative = path.relative_to(root).as_posix()
        previous = _git_json(root, base_ref, relative)
        if previous is None:
            continue
        current = json.loads(path.read_text(encoding="utf-8"))
        errors.extend(compare_strategy_payloads(previous, current, relative))
    return errors


def _contains_strategy_comparison(path: Path, strategy_ids: set[str]) -> list[int]:
    """识别 `strategy_id == 具体策略` 形式的公共模块特殊分支。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        values = [node.left, *node.comparators]
        constants = {item.value for item in values if isinstance(item, ast.Constant) and isinstance(item.value, str)}
        names = {
            item.id for item in values if isinstance(item, ast.Name)
        } | {
            item.attr for item in values if isinstance(item, ast.Attribute)
        }
        if "strategy_id" in names and constants.intersection(strategy_ids):
            lines.append(node.lineno)
    return lines


def check_special_branches(root: Path, strategy_ids: set[str]) -> list[str]:
    """公共运行模块不得按具体策略ID分支。"""
    errors: list[str] = []
    for relative in GENERIC_RUNTIME_FILES:
        path = root / relative
        if not path.exists():
            continue
        for line in _contains_strategy_comparison(path, strategy_ids):
            errors.append(f"{relative}:{line}: 公共模块不得按具体 strategy_id 分支")
    return errors


def run_checks(root: Path, base_ref: str) -> list[str]:
    """校验声明可加载、版本提升和公共模块纯度。"""
    definitions = load_strategy_definitions(root / "config" / "strategies")
    strategy_ids = {item.strategy_id for item in definitions}
    errors = check_version_bumps(root, base_ref)
    errors.extend(check_special_branches(root, strategy_ids))
    return sorted(errors)


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--base-ref", default=os.environ.get("GUARDRAIL_BASE_REF", "HEAD"))
    args = parser.parse_args()
    errors = run_checks(Path(args.root).resolve(), args.base_ref)
    if errors:
        print("策略围栏检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("策略围栏检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
