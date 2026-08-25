from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping


CLASSIFICATION_ORDER = [
    "source_code",
    "governance_docs",
    "deleted_legacy",
    "tracked_runtime_artifact",
    "runtime_data",
    "ignored_generated",
    "manual_review",
]

RUNTIME_PREFIXES = ("data/", "runs/", "logs/", "state/", "runtime_backups/")
REPORT_RUNTIME_SUFFIXES = (".json", ".csv", ".html")
SOURCE_PREFIXES = (
    "api/",
    "backtest/",
    "data/",
    "frontend/",
    "monitoring/",
    "runtime/",
    "scripts/",
    "strategies/",
    "tests/",
)
SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".css", ".md", ".html")
DATA_SUFFIXES = (
    ".duckdb",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".parquet",
    ".feather",
    ".csv",
    ".log",
    ".tar.gz",
    ".gz",
)


@dataclass(frozen=True)
class GitStatusEntry:
    """Git 工作区条目，保留状态、路径和提交分类。"""

    status: str
    path: str
    classification: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def classify_git_path(path: str, status: str = "") -> str:
    """按项目治理规则给 Git 路径分类，避免运行数据混入源码提交。"""

    normalized_status = status.strip()
    normalized_path = path.strip()
    if normalized_status == "!!":
        return "ignored_generated"
    if normalized_status == "D":
        return "deleted_legacy"
    if (
        normalized_path == ".gitignore"
        or normalized_path.startswith(".planning/")
        or normalized_path.startswith("docs/")
    ):
        return "governance_docs"
    if normalized_path.startswith("reports/") and normalized_status != "??":
        return "tracked_runtime_artifact"
    if _is_runtime_data(normalized_path):
        return "runtime_data"
    if normalized_path.startswith("reports/"):
        return "tracked_runtime_artifact"
    if _is_source_code(normalized_path):
        return "source_code"
    return "manual_review"


def parse_status_lines(lines: Iterable[str]) -> list[GitStatusEntry]:
    """解析 `git status --short` 输出，兼容普通、未跟踪和忽略文件。"""

    entries: list[GitStatusEntry] = []
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            continue
        status = line[:2].strip() or line[:2]
        path = line[3:].strip() if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path:
            continue
        entries.append(
            GitStatusEntry(
                status=status,
                path=path,
                classification=classify_git_path(path, status),
            )
        )
    return entries


def summarize_entries(
    entries: Iterable[GitStatusEntry],
) -> dict[str, list[GitStatusEntry]]:
    grouped: dict[str, list[GitStatusEntry]] = {
        name: [] for name in CLASSIFICATION_ORDER
    }
    for entry in entries:
        grouped.setdefault(entry.classification, []).append(entry)
    return grouped


def build_git_baseline_report(
    repo_root: Path,
    include_ignored: bool = True,
) -> dict[str, object]:
    root = repo_root.resolve()
    lines = _git_status_lines(root, ["status", "--short"])
    if include_ignored:
        lines.extend(_git_status_lines(root, ["status", "--ignored", "--short"]))
    entries = _dedupe_entries(parse_status_lines(lines))
    grouped = summarize_entries(entries)
    return {
        "repo_root": str(root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {key: len(value) for key, value in grouped.items()},
        "groups": {
            key: [entry.to_dict() for entry in value]
            for key, value in grouped.items()
        },
    }


def write_git_baseline_report(
    report: Mapping[str, object],
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "git_baseline_report.json"
    markdown_path = output_dir / "git_baseline_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def _is_runtime_data(path: str) -> bool:
    if path.startswith(RUNTIME_PREFIXES):
        return not (path.startswith("data/") and path.endswith(".py"))
    if path.startswith("reports/") and path.endswith(REPORT_RUNTIME_SUFFIXES):
        return True
    return path.endswith(DATA_SUFFIXES)


def _is_source_code(path: str) -> bool:
    return path.startswith(SOURCE_PREFIXES) and (
        path.endswith(SOURCE_SUFFIXES) or path.endswith("/")
    )


def _git_status_lines(repo_root: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.splitlines()


def _dedupe_entries(entries: Iterable[GitStatusEntry]) -> list[GitStatusEntry]:
    by_path: dict[str, GitStatusEntry] = {}
    for entry in entries:
        existing = by_path.get(entry.path)
        if existing is None or existing.status == "!!":
            by_path[entry.path] = entry
    return sorted(by_path.values(), key=lambda item: (item.classification, item.path))


def _render_markdown(report: Mapping[str, object]) -> str:
    summary = report.get("summary", {})
    groups = report.get("groups", {})
    lines = [
        "# Git Baseline Report",
        "",
        f"- repo_root: `{report.get('repo_root', '')}`",
        f"- generated_at: `{report.get('generated_at', '')}`",
        "",
        "## Summary",
        "",
        "| 分类 | 数量 | 提交建议 |",
        "|---|---:|---|",
    ]
    advice = {
        "source_code": "可作为代码提交候选，仍需人工 review",
        "governance_docs": "可作为治理文档提交候选",
        "deleted_legacy": "删除类变更，提交前必须确认无运行依赖",
        "tracked_runtime_artifact": "已跟踪运行产物，提交前必须逐项确认",
        "runtime_data": "运行数据，不建议提交",
        "ignored_generated": "已忽略生成物，不应提交",
        "manual_review": "未知类型，必须人工确认",
    }
    for name in CLASSIFICATION_ORDER:
        count = summary.get(name, 0) if isinstance(summary, Mapping) else 0
        lines.append(f"| `{name}` | {count} | {advice[name]} |")
    lines.append("")
    lines.append("## Groups")
    lines.append("")
    if isinstance(groups, Mapping):
        for name in CLASSIFICATION_ORDER:
            lines.append(f"### {name}")
            lines.append("")
            items = groups.get(name, [])
            if not items:
                lines.append("- 无")
            elif isinstance(items, list):
                for item in items:
                    if isinstance(item, Mapping):
                        lines.append(
                            f"- `{item.get('status', '')}` `{item.get('path', '')}`"
                        )
            lines.append("")
    return "\n".join(lines)
