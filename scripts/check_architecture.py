#!/usr/bin/env python3
"""检查模块依赖、文件大小和唯一运行入口。"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Iterable


SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".css"}
STRATEGY_CORE_FILES = {
    "backtest/strategy.py",
    "backtest/strategies.py",
    "backtest/price_factor_strategies.py",
    "backtest/rotation.py",
    "backtest/chain_selection.py",
}
DAILY_PIPELINE_ALLOWED_IMPORTERS = {"runtime/pipeline_service.py"}


def load_rules(root: Path) -> dict[str, object]:
    """读取机器可执行的架构规则。"""
    path = root / "config" / "architecture_rules.json"
    return json.loads(path.read_text(encoding="utf-8"))


def iter_source_files(root: Path) -> list[Path]:
    """返回需要检查的源码，排除缓存和依赖目录。"""
    directories = ["api", "backtest", "data", "domain", "factors", "monitoring", "portfolio", "risk", "runtime", "scripts", "strategies", "frontend/src"]
    files: list[Path] = []
    for directory in directories:
        base = root / directory
        if not base.exists():
            continue
        files.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in SOURCE_SUFFIXES
            and "__pycache__" not in path.parts
            and "node_modules" not in path.parts
        )
    return sorted(files)


def imported_modules(path: Path) -> set[str]:
    """用 AST 提取 Python 顶层依赖，避免字符串误判。"""
    if path.suffix != ".py":
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _matches_module(module: str, forbidden: str) -> bool:
    return module == forbidden or module.startswith(f"{forbidden}.")


def check_forbidden_imports(
    files: Iterable[Path],
    forbidden_modules: Iterable[str],
    root: Path,
) -> list[str]:
    """检查一组文件是否依赖了禁止模块。"""
    errors: list[str] = []
    forbidden = list(forbidden_modules)
    for path in files:
        relative = path.relative_to(root).as_posix()
        for module in sorted(imported_modules(path)):
            matched = next((item for item in forbidden if _matches_module(module, item)), None)
            if matched:
                errors.append(f"{relative}: 禁止依赖 {matched}")
    return errors


def check_file_size(
    files: Iterable[Path],
    max_lines: int,
    allowlist: dict[str, str],
    root: Path,
) -> list[str]:
    """限制源码行数，同时保留有说明的历史债务。"""
    errors: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        if relative in allowlist:
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > max_lines:
            errors.append(f"{relative}: {line_count} 行，超过 {max_lines} 行限制")
    return errors


def check_unique_daily_pipeline_import(root: Path, files: Iterable[Path]) -> list[str]:
    """只有 PipelineService 可以依赖每日流水线业务实现。"""
    errors: list[str] = []
    for path in files:
        if path.suffix != ".py":
            continue
        relative = path.relative_to(root).as_posix()
        if relative in DAILY_PIPELINE_ALLOWED_IMPORTERS:
            continue
        if any(_matches_module(module, "runtime.daily_pipeline") for module in imported_modules(path)):
            errors.append(f"{relative}: 必须通过 runtime.pipeline_service 调用每日流水线")
    return errors


def check_frontend_storage_access(root: Path, files: Iterable[Path]) -> list[str]:
    """前端只允许调用 API，不得读取本地存储路径。"""
    errors: list[str] = []
    # 文件名可以作为 API 返回的展示字段，真正禁止的是浏览器侧文件/数据库访问能力。
    forbidden_tokens = ("file://", "readFileSync(", "node:fs", "duckdb.connect(", "sqlite3.Database(")
    for path in files:
        relative = path.relative_to(root).as_posix()
        if not relative.startswith("frontend/src/"):
            continue
        content = path.read_text(encoding="utf-8")
        token = next((item for item in forbidden_tokens if item in content), None)
        if token:
            errors.append(f"{relative}: 前端不得直接访问本地存储标识 {token}")
    return errors


def run_checks(root: Path) -> list[str]:
    """执行全部架构围栏并返回稳定错误列表。"""
    rules = load_rules(root)
    files = iter_source_files(root)
    forbidden = dict(rules.get("forbidden_imports", {}))
    api_files = [path for path in files if path.relative_to(root).as_posix().startswith("api/")]
    strategy_core = [path for path in files if path.relative_to(root).as_posix() in STRATEGY_CORE_FILES]
    strategy_runners = [path for path in files if path.relative_to(root).as_posix().startswith("strategies/")]
    errors = check_file_size(
        files,
        int(rules.get("max_file_lines", 500)),
        dict(rules.get("oversized_file_allowlist", {})),
        root,
    )
    errors.extend(check_forbidden_imports(api_files, forbidden.get("api", []), root))
    errors.extend(check_forbidden_imports(strategy_core, forbidden.get("strategy_core", []), root))
    errors.extend(check_forbidden_imports(strategy_runners, forbidden.get("strategy_runners", []), root))
    errors.extend(check_unique_daily_pipeline_import(root, files))
    errors.extend(check_frontend_storage_access(root, files))
    return sorted(set(errors))


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    errors = run_checks(Path(args.root).resolve())
    if errors:
        print("架构围栏检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("架构围栏检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
