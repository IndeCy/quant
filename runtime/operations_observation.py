from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

from runtime.notification_config import resolve_bark_url


REQUIRED_RUN_ARTIFACTS = (
    "daily_report.md",
    "strategy_metrics.json",
    "portfolio_snapshot.csv",
    "rebalance_plan.csv",
    "run_log.txt",
)


def build_operations_observation(repo_root: Path) -> dict[str, object]:
    """生成长期观察摘要，只读取本地状态，不触发任何运行任务。"""

    root = repo_root.resolve()
    latest_activity_date = _latest_activity_date(root / "runs")
    latest_activity_type = _run_type(root / "runs" / latest_activity_date) if latest_activity_date else ""
    latest_run_date = _latest_complete_run_date(root / "runs")
    run_artifacts = _run_artifacts(root, latest_run_date)
    scheduler = _scheduler_evidence(root)
    reports = _held_reports(root)
    notification = _notification_evidence()
    summary = _summary([run_artifacts, scheduler, reports, notification])
    return {
        "repo_root": str(root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "latest_activity_date": latest_activity_date,
        "latest_activity_type": latest_activity_type,
        "latest_run_date": latest_run_date,
        "summary": summary,
        "run_artifacts": run_artifacts,
        "scheduler": scheduler,
        "notification": notification,
        "held_reports": reports,
        "ready_for_daily_review": summary["fail"] == 0,
    }


def write_operations_observation(
    report: Mapping[str, object],
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "operations_observation_summary.md"
    json_path = output_dir / "operations_observation_summary.json"
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {"markdown": markdown_path, "json": json_path}


def _latest_activity_date(runs_dir: Path) -> str:
    if not runs_dir.exists():
        return ""
    dates = sorted(path.name for path in runs_dir.iterdir() if path.is_dir() and path.name.isdigit())
    return dates[-1] if dates else ""


def _latest_complete_run_date(runs_dir: Path) -> str:
    if not runs_dir.exists():
        return ""
    dates = sorted(path.name for path in runs_dir.iterdir() if path.is_dir() and path.name.isdigit())
    for day in reversed(dates):
        if _run_type(runs_dir / day) == "complete_daily_run":
            return day
    return dates[-1] if dates else ""


def _run_type(run_dir: Path) -> str:
    if all((run_dir / name).exists() for name in REQUIRED_RUN_ARTIFACTS):
        return "complete_daily_run"
    if (run_dir / "pre_market_check.md").exists() or (run_dir / "execution_checklist.csv").exists():
        return "pre_market_only"
    return "partial_activity"


def _run_artifacts(root: Path, latest_run_date: str) -> dict[str, str]:
    if not latest_run_date:
        return {name: "WARN" for name in REQUIRED_RUN_ARTIFACTS}
    run_dir = root / "runs" / latest_run_date
    return {
        name: "PASS" if (run_dir / name).exists() else "WARN"
        for name in REQUIRED_RUN_ARTIFACTS
    }


def _scheduler_evidence(root: Path) -> dict[str, str]:
    state_dir = root / "state"
    logs_dir = root / "logs"
    return {
        "heartbeat": "PASS" if (state_dir / "scheduler.heartbeat").exists() else "WARN",
        "state_db": "PASS" if (state_dir / "scheduler.sqlite").exists() else "WARN",
        "scheduler_log": "PASS" if (logs_dir / "scheduler.log").exists() else "WARN",
    }


def _held_reports(root: Path) -> dict[str, str]:
    reports_dir = root / "reports"
    names = ("dashboard.html", "dashboard_data.json", "quality_overlay_paper_latest.md")
    return {name: "PASS" if (reports_dir / name).exists() else "WARN" for name in names}


def _notification_evidence() -> dict[str, object]:
    configured = bool(resolve_bark_url())
    return {
        "configured": configured,
        "status": "PASS" if configured else "WARN",
        "details": "Bark 已配置" if configured else "Bark 未配置，本机仅保留本地报告",
    }


def _summary(sections: list[Mapping[str, object]]) -> dict[str, int]:
    summary = {"pass": 0, "warn": 0, "fail": 0}
    for section in sections:
        for value in section.values():
            status = _status_from_value(value)
            if status:
                summary[status.lower()] += 1
    return summary


def _status_from_value(value: object) -> str:
    if isinstance(value, str) and value in {"PASS", "WARN", "FAIL"}:
        return value
    if isinstance(value, bool):
        return "PASS" if value else ""
    return ""


def _render_markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# Operations Observation Summary",
        "",
        f"- repo_root: `{report.get('repo_root', '')}`",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- latest_activity_date: `{report.get('latest_activity_date', '')}`",
        f"- latest_activity_type: `{report.get('latest_activity_type', '')}`",
        f"- latest_run_date: `{report.get('latest_run_date', '')}`",
        f"- ready_for_daily_review: `{report.get('ready_for_daily_review')}`",
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
    for title, key in [
        ("Run Artifacts", "run_artifacts"),
        ("Scheduler", "scheduler"),
        ("Notification", "notification"),
        ("Held Reports", "held_reports"),
    ]:
        lines.extend(["", f"## {title}", "", "| 项目 | 状态 |", "|---|---|"])
        section = report.get(key, {})
        if isinstance(section, Mapping):
            for name, status in section.items():
                lines.append(f"| `{name}` | {status} |")
    lines.append("")
    return "\n".join(lines)
