"""ETF 折溢价监控任务的 APScheduler 登记。"""

from __future__ import annotations

from pathlib import Path
import sys

from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.scheduler import project_root, run_daily_pipeline


ETF_PREMIUM_MONITOR_JOB_ID = "etf_513500_premium_monitor"
DEFAULT_MONITOR_CONFIG = "config/etf_monitors/513500.json"
ETF_MONITOR_JOBS = (
    (ETF_PREMIUM_MONITOR_JOB_ID, DEFAULT_MONITOR_CONFIG, "*/5"),
    ("etf_518880_allocation_monitor", "config/etf_monitors/518880.json", "*/15"),
    ("etf_511010_allocation_monitor", "config/etf_monitors/511010.json", "*/15"),
)


def build_etf_premium_monitor_command(
    python_executable: str = sys.executable,
    *,
    push: bool = False,
    config_path: str = DEFAULT_MONITOR_CONFIG,
) -> list[str]:
    """构造只提醒、不交易的监控命令。"""
    command = [
        python_executable,
        "scripts/run_etf_premium_monitor.py",
        "--config",
        config_path,
    ]
    if push:
        command.append("--push")
    return command


def install_etf_premium_monitor_job(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    *,
    push: bool = False,
    job_id: str = ETF_PREMIUM_MONITOR_JOB_ID,
    config_path: str = DEFAULT_MONITOR_CONFIG,
    minute: str = "*/5",
) -> Job:
    """每5分钟唤醒；脚本自身会跳过非盘中窗口。"""
    runtime_paths = paths or get_runtime_paths()
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour="9-11,13-14",
        minute=minute,
        id=job_id,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
        kwargs={
            "command": build_etf_premium_monitor_command(push=push, config_path=config_path),
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / f"etf_premium_monitor_{Path(config_path).stem}.log"),
        },
    )


def install_etf_premium_monitor_jobs(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    *,
    push: bool = False,
) -> list[Job]:
    """登记标普、黄金和国债三个只提醒的配置监控。"""
    return [
        install_etf_premium_monitor_job(
            scheduler,
            paths,
            push=push,
            job_id=job_id,
            config_path=config_path,
            minute=minute,
        )
        for job_id, config_path, minute in ETF_MONITOR_JOBS
    ]


def monitor_config_path() -> Path:
    return project_root() / DEFAULT_MONITOR_CONFIG
