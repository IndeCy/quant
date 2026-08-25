from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


STAGE_GROUPS = ("source_code", "governance_docs", "deleted_legacy")
EXCLUDED_GROUPS = ("runtime_data", "ignored_generated")
HOLD_GROUPS = ("tracked_runtime_artifact",)


def build_safe_commit_review(baseline: Mapping[str, object]) -> dict[str, object]:
    """从 Git 基线报告生成可选择提交的安全清单。"""

    groups = baseline.get("groups", {})
    if not isinstance(groups, Mapping):
        groups = {}
    stage_candidates = _paths_from_groups(groups, STAGE_GROUPS)
    git_update_candidates = _paths_by_status(groups, STAGE_GROUPS, "D")
    git_add_candidates = sorted(
        path for path in stage_candidates if path not in set(git_update_candidates)
    )
    excluded_runtime = _paths_from_groups(groups, EXCLUDED_GROUPS)
    hold_for_review = _paths_from_groups(groups, HOLD_GROUPS)
    manual_review = _paths_from_groups(groups, ("manual_review",))
    return {
        "repo_root": baseline.get("repo_root", ""),
        "baseline_generated_at": baseline.get("generated_at", ""),
        "stage_candidates": stage_candidates,
        "git_add_candidates": git_add_candidates,
        "git_update_candidates": git_update_candidates,
        "excluded_runtime": excluded_runtime,
        "hold_for_review": hold_for_review,
        "manual_review": manual_review,
        "ready_for_selective_commit": len(manual_review) == 0,
        "safe_git_add_command": _build_git_add_command(git_add_candidates),
        "safe_git_update_command": _build_git_update_command(git_update_candidates),
        "notes": [
            "只使用 safe_git_add_command 和 safe_git_update_command 进行选择性暂存。",
            "不要执行 git add -A，避免运行数据和报告产物进入提交。",
            "hold_for_review 中的已跟踪运行产物需单独决定保留或回滚。",
        ],
    }


def render_safe_commit_markdown(review: Mapping[str, object]) -> str:
    lines = [
        "# Safe Commit Review",
        "",
        f"- repo_root: `{review.get('repo_root', '')}`",
        f"- baseline_generated_at: `{review.get('baseline_generated_at', '')}`",
        f"- ready_for_selective_commit: `{review.get('ready_for_selective_commit')}`",
        "",
        "## Safe Git Add",
        "",
        str(review.get("safe_git_add_command", "") or "# no stage candidates"),
        "",
        "## Safe Git Update",
        "",
        str(review.get("safe_git_update_command", "") or "# no deleted candidates"),
        "",
    ]
    sections = [
        ("Stage Candidates", "stage_candidates"),
        ("Hold For Review", "hold_for_review"),
        ("Excluded Runtime", "excluded_runtime"),
        ("Manual Review", "manual_review"),
    ]
    for title, key in sections:
        lines.extend([f"## {title}", ""])
        items = review.get(key, [])
        if isinstance(items, list) and items:
            lines.extend(f"- `{item}`" for item in items)
        else:
            lines.append("- 无")
        lines.append("")
    lines.extend(
        [
            "## Notes",
            "",
            "- 选择性提交前先阅读本报告和 Git diff。",
            "- 运行数据、备份包、日报输出不进入代码发布基线。",
            "- 已跟踪报告产物不自动处理，避免误删用户需要保留的本地观察结果。",
            "",
        ]
    )
    return "\n".join(lines)


def write_safe_commit_review(
    review: Mapping[str, object],
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "safe_commit_review.md"
    json_path = output_dir / "safe_commit_review.json"
    markdown_path.write_text(render_safe_commit_markdown(review), encoding="utf-8")
    json_path.write_text(
        json.dumps(review, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {"markdown": markdown_path, "json": json_path}


def _paths_from_groups(
    groups: Mapping[object, object],
    names: tuple[str, ...],
) -> list[str]:
    paths: list[str] = []
    for name in names:
        items = groups.get(name, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, Mapping):
                path = item.get("path")
                if isinstance(path, str) and path:
                    paths.append(path)
    return sorted(dict.fromkeys(paths))


def _build_git_add_command(paths: list[str]) -> str:
    if not paths:
        return ""
    quoted = " ".join(_shell_quote_path(path) for path in paths)
    return f"git add -- {quoted}"


def _build_git_update_command(paths: list[str]) -> str:
    if not paths:
        return ""
    quoted = " ".join(_shell_quote_path(path) for path in paths)
    return f"git rm --cached --ignore-unmatch -- {quoted}"


def _paths_by_status(
    groups: Mapping[object, object],
    names: tuple[str, ...],
    status: str,
) -> list[str]:
    paths: list[str] = []
    for name in names:
        items = groups.get(name, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, Mapping) and item.get("status") == status:
                path = item.get("path")
                if isinstance(path, str) and path:
                    paths.append(path)
    return sorted(dict.fromkeys(paths))


def _shell_quote_path(path: str) -> str:
    escaped = path.replace("'", "'\"'\"'")
    return f"'{escaped}'"
