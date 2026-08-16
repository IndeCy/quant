"""组合重平衡提醒的 APScheduler 登记。"""

from __future__ import annotations

import sys

from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.scheduler import project_root, run_daily_pipeline


PORTFOLIO_REBALANCE_JOB_ID = "portfolio_rebalance_monitor"
DEFAULT_REBALANCE_CONFIG = "config/portfolio_rebalance.json"


def build_portfolio_rebalance_command(
    python_executable: str = sys.executable,
    *,
    push: bool = False,
) -> list[str]:
    command = [
        python_executable,
        "scripts/run_portfolio_rebalance_monitor.py",
        "--config",
        DEFAULT_REBALANCE_CONFIG,
    ]
    if push:
        command.append("--push")
    return command


def install_portfolio_rebalance_job(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    *,
    push: bool = False,
) -> Job:
    """交易日盘前用前收盘权重检查建仓缺口与重平衡带。"""
    runtime_paths = paths or get_runtime_paths()
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=9,
        minute=25,
        id=PORTFOLIO_REBALANCE_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=15 * 60,
        kwargs={
            "command": build_portfolio_rebalance_command(push=push),
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / "portfolio_rebalance_monitor.log"),
        },
    )
