#!/usr/bin/env python3
"""检查研究指纹声明的风险层与实际回测调用是否一致。"""

from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_PATTERNS = ("*_study.py", "*_research.py")
GRID_KEYS = {"threshold", "reduced_exposure"}
MODE_KEYS = ("scheme", "mode", "implementation_scheme")


def find_research_risk_errors(root: Path) -> list[str]:
    """扫描研究入口，返回风险层声明缺失或实现错配。"""
    errors: list[str] = []
    for path in _research_files(root):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            errors.append(f"{path.relative_to(root)}: 无法解析: {error}")
            continue
        constants = _string_constants(tree)
        declarations = _risk_declarations(tree, constants)
        calls = _risk_calls(tree, constants)
        call_modes = {mode for mode, _, _ in calls if mode is not None}
        relative = path.relative_to(root)

        for mode, line, keywords in calls:
            if (
                mode == "FIXED"
                and {"vol_threshold", "reduced_exposure"}.issubset(keywords)
            ):
                errors.append(
                    f"{relative}:{line}: FIXED 会忽略波动率阈值参数，应使用 GRID"
                )
        for line, mode, implicit_grid in declarations:
            if implicit_grid:
                errors.append(
                    f"{relative}:{line}: 波动率风险层必须显式声明 scheme/mode=GRID"
                )
            if mode == "GRID" and "FIXED" in call_modes:
                errors.append(
                    f"{relative}: 声明 GRID 风险层但实际调用 FIXED"
                )
            if mode in {"NONE", "FIXED"} and "GRID" in call_modes:
                errors.append(
                    f"{relative}: 声明无风险覆盖层但实际调用 GRID"
                )
    return sorted(set(errors))


def _research_files(root: Path) -> list[Path]:
    """返回去重后的研究入口文件。"""
    files: set[Path] = set()
    examples = root / "examples"
    for pattern in RESEARCH_PATTERNS:
        files.update(examples.glob(pattern))
    return sorted(files)


def _string_constants(tree: ast.AST) -> dict[str, str]:
    """解析模块级字符串常量，支持 RISK_SCHEME 绑定。"""
    result: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(
            value.value,
            str,
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                result[target.id] = value.value.upper()
    return result


def _risk_declarations(
    tree: ast.AST,
    constants: dict[str, str],
) -> list[tuple[int, str | None, bool]]:
    """读取字典中的 risk_overlay 声明。"""
    declarations: list[tuple[int, str | None, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (
                isinstance(key, ast.Constant)
                and key.value == "risk_overlay"
            ):
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                declarations.append(
                    (value.lineno, _normalize_mode(value.value), False)
                )
                continue
            if not isinstance(value, ast.Dict):
                continue
            fields = {
                str(item.value): field_value
                for item, field_value in zip(value.keys, value.values)
                if isinstance(item, ast.Constant)
            }
            mode = next(
                (
                    _node_string(fields[name], constants)
                    for name in MODE_KEYS
                    if name in fields
                ),
                None,
            )
            implicit_grid = GRID_KEYS.issubset(fields) and mode is None
            declarations.append((value.lineno, _normalize_mode(mode), implicit_grid))
    return declarations


def _risk_calls(
    tree: ast.AST,
    constants: dict[str, str],
) -> list[tuple[str | None, int, set[str]]]:
    """读取回测器模式、行号和关键字参数。"""
    calls: list[tuple[str | None, int, set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else getattr(node.func, "attr", "")
        )
        if name != "run_risk_layer_backtest":
            continue
        mode = _node_string(node.args[1], constants)
        normalized = _normalize_mode(mode)
        calls.append(
            (
                normalized,
                node.lineno,
                {
                    str(keyword.arg)
                    for keyword in node.keywords
                    if keyword.arg is not None
                },
            )
        )
    return calls


def _node_string(
    node: ast.AST,
    constants: dict[str, str],
) -> str | None:
    """解析字符串字面量或模块级字符串常量。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _normalize_mode(value: str | None) -> str | None:
    """统一风险层模式别名。"""
    if value is None:
        return None
    normalized = value.upper()
    if normalized in {"NONE", "NO", "DISABLED"}:
        return "NONE"
    return normalized


def main() -> int:
    """执行检查并返回稳定退出码。"""
    errors = find_research_risk_errors(ROOT)
    if errors:
        print("研究风险层一致性检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("研究风险层一致性检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
