from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_REQUIRED_SCRIPTS = [
    "scripts/run_daily_pipeline.py",
    "scripts/run_strategy_batch.py",
    "scripts/run_data_quality_gate.py",
    "scripts/run_research_monitor.py",
    "scripts/run_scheduler_watchdog.py",
    "scripts/restart_services.sh",
]


@dataclass(frozen=True)
class AuditCheck:
    """基线后运行观察检查项。"""

    name: str
    status: str
    details: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def build_post_baseline_audit(
    repo_root: Path,
    required_scripts: Iterable[str] | None = None,
) -> dict[str, object]:
    root = repo_root.resolve()
    scripts = list(DEFAULT_REQUIRED_SCRIPTS if required_scripts is None else required_scripts)
    checks = [
        _required_scripts_check(root, scripts),
        _runtime_outputs_check(root),
        _held_report_artifacts_check(root),
        _git_runtime_boundary_check(root),
        _baseline_commit_check(root),
    ]
    summary = _summary(checks)
    return {
        "repo_root": str(root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "checks": [check.to_dict() for check in checks],
        "ready_for_observation": summary["fail"] == 0,
    }


def write_post_baseline_audit(
    report: Mapping[str, object],
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "post_baseline_operations_audit.md"
    json_path = output_dir / "post_baseline_operations_audit.json"
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {"markdown": markdown_path, "json": json_path}


def _required_scripts_check(root: Path, required_scripts: list[str]) -> AuditCheck:
    missing = [script for script in required_scripts if not (root / script).exists()]
    if missing:
        return AuditCheck("required_scripts", "FAIL", ", ".join(missing))
    return AuditCheck("required_scripts", "PASS", f"{len(required_scripts)} 个运行入口存在")


def _runtime_outputs_check(root: Path) -> AuditCheck:
    runs_dir = root / "runs"
    if not runs_dir.exists():
        return AuditCheck("runtime_outputs_present", "WARN", "runs 目录不存在，尚无可观察日报产物")
    run_days = sorted(path.name for path in runs_dir.iterdir() if path.is_dir() and path.name.isdigit())
    if not run_days:
        return AuditCheck("runtime_outputs_present", "WARN", "runs 目录存在，但未发现交易日目录")
    return AuditCheck("runtime_outputs_present", "PASS", f"发现 {len(run_days)} 个运行日，最新 {run_days[-1]}")


def _held_report_artifacts_check(root: Path) -> AuditCheck:
    report_paths = [
        root / "reports" / "dashboard.html",
        root / "reports" / "dashboard_data.json",
        root / "reports" / "quality_overlay_paper_latest.md",
    ]
    existing = [path.name for path in report_paths if path.exists()]
    if not existing:
        return AuditCheck("held_report_artifacts", "WARN", "未发现本地看板报告产物")
    return AuditCheck("held_report_artifacts", "PASS", ", ".join(existing))


def _git_runtime_boundary_check(root: Path) -> AuditCheck:
    if not (root / ".git").exists():
        return AuditCheck("git_runtime_boundary", "WARN", "非 Git 仓库，跳过提交边界检查")
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    staged_runtime = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        index_status = line[:1]
        is_untracked = line.startswith("??")
        if index_status != " " and not is_untracked and _is_runtime_path(path):
            staged_runtime.append(path)
    if staged_runtime:
        return AuditCheck("git_runtime_boundary", "FAIL", ", ".join(staged_runtime))
    return AuditCheck("git_runtime_boundary", "PASS", "未发现已暂存运行数据")


def _baseline_commit_check(root: Path) -> AuditCheck:
    if not (root / ".git").exists():
        return AuditCheck("baseline_commit", "WARN", "非 Git 仓库，跳过提交检查")
    result = subprocess.run(
        ["git", "log", "-1", "--oneline"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return AuditCheck("baseline_commit", "WARN", "未发现提交记录")
    line = result.stdout.strip()
    if not line:
        return AuditCheck("baseline_commit", "WARN", "未发现提交记录")
    return AuditCheck("baseline_commit", "PASS", line)


def _is_runtime_path(path: str) -> bool:
    return (
        path.startswith("runs/")
        or path.startswith("runtime_backups/")
        or path.endswith(".duckdb")
        or path.endswith(".sqlite")
        or path.endswith(".sqlite3")
    )


def _summary(checks: list[AuditCheck]) -> dict[str, int]:
    summary = {"pass": 0, "warn": 0, "fail": 0}
    for check in checks:
        summary[check.status.lower()] += 1
    return summary


def _render_markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# Post-Baseline Operations Audit",
        "",
        f"- repo_root: `{report.get('repo_root', '')}`",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- ready_for_observation: `{report.get('ready_for_observation')}`",
        "",
        "## Summary",
        "",
    ]
    summary = report.get("summary", {})
    if isinstance(summary, Mapping):
        lines.extend(
            [
                f"- PASS: {summary.get('pass', 0)}",
                f"- WARN: {summary.get('warn', 0)}",
                f"- FAIL: {summary.get('fail', 0)}",
            ]
        )
    lines.extend(["", "## Checks", "", "| 检查项 | 状态 | 证据 |", "|---|---|---|"])
    checks = report.get("checks", [])
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, Mapping):
                lines.append(
                    f"| `{check.get('name', '')}` | {check.get('status', '')} | {check.get('details', '')} |"
                )
    lines.append("")
    return "\n".join(lines)
