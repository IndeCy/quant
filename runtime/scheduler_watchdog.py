"""调度稳定性巡检。

只在发现异常时发送 Bark，正常情况下只记录本地运行结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3

from monitoring.repository import MonitoringRepository
from runtime.notification_config import send_bark_notification
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.strategy_commit_journal import StrategyCommitJournalRepository


WATCHDOG_ID = "scheduler_watchdog"
REQUIRED_PIPELINE_STEPS = ("data_update", "data_notification", "strategy_batch", "notification")


@dataclass(frozen=True)
class WatchdogResult:
    """巡检结果。"""

    trade_date: str
    status: str
    issue_count: int
    issues: list[str]


def run_scheduler_watchdog(
    paths: RuntimePaths | None = None,
    push: bool = False,
    trade_date: str | None = None,
) -> WatchdogResult:
    """检查当天调度是否完整运行，只有异常时才发 Bark。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    target_date = trade_date or _today()
    repository = SystemRepository(runtime_paths.system_state_path)
    issues = _collect_issues(runtime_paths, repository, target_date)
    status = "FAILED" if issues else "SUCCESS"
    message = _format_watchdog_message(target_date, issues)
    run_dir = runtime_paths.runs_dir / target_date
    repository.record_strategy_run(WATCHDOG_ID, target_date, status, run_dir, message)
    if issues and push:
        send_bark_notification("量化调度异常", message)
    return WatchdogResult(trade_date=target_date, status=status, issue_count=len(issues), issues=issues)


def _collect_issues(paths: RuntimePaths, repository: SystemRepository, trade_date: str) -> list[str]:
    issues: list[str] = []
    incomplete_commits = StrategyCommitJournalRepository(paths.system_state_path).list_incomplete()
    for commit in incomplete_commits:
        issues.append(
            "策略提交未完成: "
            f"{commit['strategy_id']} {commit['trade_date']} "
            f"{commit['status']}@{commit['last_step']}"
        )
    pipeline = repository.get_run("daily_trading_pipeline", trade_date)
    if not pipeline or pipeline.get("status") != "SUCCESS":
        issues.append("daily_trading_pipeline 未成功运行")
    steps = {item["step_name"]: item["status"] for item in repository.list_run_steps("daily_trading_pipeline", trade_date)}
    for step_name in REQUIRED_PIPELINE_STEPS:
        if steps.get(step_name) != "SUCCESS":
            issues.append(f"daily_trading_pipeline.{step_name} 未成功")

    for instance in repository.list_strategy_instances(enabled_only=True):
        strategy_id = str(instance["strategy_id"])
        run = repository.get_run(strategy_id, trade_date)
        if not run or run.get("status") != "SUCCESS":
            issues.append(f"{strategy_id} 未成功运行")

    monitoring = MonitoringRepository(paths.monitoring_path)
    for instance in repository.list_strategy_instances(enabled_only=True):
        strategy_id = str(instance["strategy_id"])
        if not _has_strategy_metrics_on_date(monitoring, strategy_id, trade_date):
            issues.append(f"{strategy_id} 监控净值未更新到 {trade_date}")

    if not repository.list_opportunity_direction_rankings(trade_date):
        issues.append("research_monitor 未生成今日投研排行")
    if not _has_research_monitor_success(paths, trade_date):
        issues.append("research_monitor 未成功运行")
    return issues


def _has_research_monitor_success(paths: RuntimePaths, trade_date: str) -> bool:
    with sqlite3.connect(paths.system_state_path) as con:
        row = con.execute(
            "SELECT COUNT(*) FROM research_monitor_runs WHERE trade_date = ? AND status = 'SUCCESS'",
            [trade_date],
        ).fetchone()
    return bool(row and int(row[0]) > 0)


def _has_strategy_metrics_on_date(monitoring: MonitoringRepository, strategy_id: str, trade_date: str) -> bool:
    history = monitoring.load_strategy_history(strategy_id)
    if history.empty:
        return False
    return bool(history["trade_date"].astype(str).eq(trade_date).any())


def _format_watchdog_message(trade_date: str, issues: list[str]) -> str:
    if not issues:
        return f"调度巡检正常: {trade_date}"
    issue_text = "\n".join(f"- {item}" for item in issues)
    return "\n".join(
        [
            f"量化调度异常 {trade_date}",
            "",
            "异常项：",
            issue_text,
            "",
            "建议：",
            "- 执行 scripts/run_daily_pipeline.py --source manual --push",
            "- 执行 scripts/run_research_monitor.py --push",
        ]
    )


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")
