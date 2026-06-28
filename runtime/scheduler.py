"""本地 APScheduler 调度器。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys

from apscheduler.job import Job
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED

from runtime.paths import RuntimePaths, get_runtime_paths


DAILY_PIPELINE_JOB_ID = "quality_overlay_daily_pipeline"
DEFAULT_HOUR = 16
DEFAULT_MINUTE = 30


def project_root() -> Path:
    """定位项目根目录，保证调度器从任意工作目录启动都能运行脚本。"""
    return Path(__file__).resolve().parents[1]


def build_daily_pipeline_command(
    python_executable: str = sys.executable,
    skip_update: bool = False,
    push: bool = False,
) -> list[str]:
    """构造每日流水线命令，复用既有脚本入口。"""
    command = [python_executable, "examples/run_quality_overlay_paper.py"]
    if skip_update:
        command.append("--skip-update")
    if push:
        command.append("--push")
    return command


def create_scheduler(paths: RuntimePaths | None = None) -> BackgroundScheduler:
    """创建使用 SQLite job store 的 APScheduler。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{runtime_paths.scheduler_state_path}"),
    }
    return BackgroundScheduler(jobstores=jobstores, timezone="Asia/Shanghai")


def install_daily_pipeline_job(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    skip_update: bool = False,
    push: bool = False,
) -> Job:
    """登记每日盘后 Quality Alpha 生产候选流水线任务。"""
    runtime_paths = paths or get_runtime_paths()
    command = build_daily_pipeline_command(skip_update=skip_update, push=push)
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id=DAILY_PIPELINE_JOB_ID,
        replace_existing=True,
        kwargs={
            "command": command,
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        },
    )


def load_scheduler_status(paths: RuntimePaths | None = None) -> dict[str, object]:
    """读取每日调度状态，不执行流水线。"""
    runtime_paths = paths or get_runtime_paths()
    scheduler = create_scheduler(runtime_paths)
    scheduler.start(paused=True)
    schedule = f"mon-fri {DEFAULT_HOUR:02d}:{DEFAULT_MINUTE:02d} Asia/Shanghai"
    start_hour = DEFAULT_HOUR
    start_minute = DEFAULT_MINUTE
    start_flags = ""
    try:
        job = scheduler.get_job(DAILY_PIPELINE_JOB_ID)
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
        if job is not None:
            schedule = _describe_cron_schedule(job)
            start_hour, start_minute = _cron_hour_minute(job)
            start_flags = _start_flags_from_job(job)
    finally:
        if scheduler.state != STATE_STOPPED:
            scheduler.shutdown()
    return {
        "enabled": job is not None,
        "job_id": DAILY_PIPELINE_JOB_ID,
        "job_store_path": str(runtime_paths.scheduler_state_path),
        "job_store_exists": runtime_paths.scheduler_state_path.exists(),
        "next_run_time": next_run,
        "schedule": schedule,
        "start_command": (
            f"{sys.executable} scripts/run_local_scheduler.py --hour {start_hour} --minute {start_minute}{start_flags}"
        ),
        "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
    }


def configure_daily_pipeline_job(
    paths: RuntimePaths | None = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    skip_update: bool = False,
    push: bool = False,
) -> dict[str, object]:
    """把每日任务写入 APScheduler job store，但不执行任务。"""
    runtime_paths = paths or get_runtime_paths()
    scheduler = create_scheduler(runtime_paths)
    scheduler.start(paused=True)
    try:
        install_daily_pipeline_job(
            scheduler,
            runtime_paths,
            hour=hour,
            minute=minute,
            skip_update=skip_update,
            push=push,
        )
    finally:
        if scheduler.state != STATE_STOPPED:
            scheduler.shutdown()
    return load_scheduler_status(runtime_paths)


def _describe_cron_schedule(job: Job) -> str:
    """从 CronTrigger 中提取面向设置页的简短描述。"""
    values = {field.name: str(field) for field in getattr(job.trigger, "fields", [])}
    day = values.get("day_of_week", "mon-fri")
    hour = values.get("hour", f"{DEFAULT_HOUR:02d}").zfill(2)
    minute = values.get("minute", f"{DEFAULT_MINUTE:02d}").zfill(2)
    timezone = getattr(job.trigger, "timezone", "Asia/Shanghai")
    return f"{day} {hour}:{minute} {timezone}"


def _cron_hour_minute(job: Job) -> tuple[int, int]:
    """读取调度任务的小时和分钟。"""
    values = {field.name: str(field) for field in getattr(job.trigger, "fields", [])}
    return int(values.get("hour", DEFAULT_HOUR)), int(values.get("minute", DEFAULT_MINUTE))


def _start_flags_from_job(job: Job) -> str:
    """从任务命令恢复调度器启动参数。"""
    command = job.kwargs.get("command", [])
    flags: list[str] = []
    if "--skip-update" in command:
        flags.append("--skip-update")
    if "--push" in command:
        flags.append("--push")
    return "" if not flags else " " + " ".join(flags)


def run_daily_pipeline(command: list[str], cwd: str, log_path: str) -> None:
    """执行每日流水线，并把 stdout/stderr 追加到调度日志。"""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as file:
        file.write(f"\n[{started_at}] START {' '.join(command)}\n")
        result = subprocess.run(command, cwd=cwd, text=True, stdout=file, stderr=subprocess.STDOUT, check=False)
        finished_at = datetime.now().isoformat(timespec="seconds")
        file.write(f"[{finished_at}] EXIT {result.returncode}\n")
    if result.returncode != 0:
        raise RuntimeError(f"daily pipeline failed with exit code {result.returncode}")
