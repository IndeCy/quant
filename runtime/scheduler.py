"""本地 APScheduler 调度器。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys

from apscheduler.job import Job
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED

from runtime.paths import RuntimePaths, get_runtime_paths


TRADING_PIPELINE_JOB_ID = "daily_trading_pipeline"
PRE_MARKET_CHECK_JOB_ID = "pre_market_check_pipeline"
MARKET_OPEN_PAPER_EXECUTION_JOB_ID = "market_open_paper_execution_pipeline"
LIVE_RISK_GUARD_JOB_ID = "live_risk_guard_pipeline"
DATA_UPDATE_JOB_ID = "daily_data_update_pipeline"
DAILY_PIPELINE_JOB_ID = "quality_overlay_daily_pipeline"
STRATEGY_BATCH_JOB_ID = "strategy_batch_pipeline"
RESEARCH_MONITOR_JOB_ID = "research_monitor_pipeline"
SCHEDULER_WATCHDOG_JOB_ID = "scheduler_watchdog_pipeline"
DEFAULT_HOUR = 16
DEFAULT_MINUTE = 30
DEFAULT_STRATEGY_DELAY_MINUTES = 10
DEFAULT_RESEARCH_DELAY_MINUTES = 15
DEFAULT_LIVE_RISK_DELAY_MINUTES = 25
DEFAULT_WATCHDOG_DELAY_MINUTES = 35
DEFAULT_PRE_MARKET_HOUR = 9
DEFAULT_PRE_MARKET_MINUTE = 20
DEFAULT_MARKET_OPEN_EXECUTION_HOUR = 9
DEFAULT_MARKET_OPEN_EXECUTION_MINUTE = 35
DEFAULT_MISFIRE_GRACE_SECONDS = 15 * 60


def project_root() -> Path:
    """定位项目根目录，保证调度器从任意工作目录启动都能运行脚本。"""
    return Path(__file__).resolve().parents[1]


def build_daily_pipeline_command(
    python_executable: str = sys.executable,
    skip_update: bool = False,
    push: bool = False,
) -> list[str]:
    """构造唯一每日交易流水线命令，调度和补跑必须复用它。"""
    command = [python_executable, "scripts/run_daily_pipeline.py", "--source", "scheduler"]
    if push:
        command.append("--push")
    return command

def build_daily_data_update_command(python_executable: str = sys.executable) -> list[str]:
    """构造统一数据更新命令，策略任务只读取更新后的缓存。"""
    return [python_executable, "scripts/run_daily_data_update.py"]


def build_strategy_batch_command(python_executable: str = sys.executable, push: bool = False) -> list[str]:
    """构造动态策略实例批量运行命令。"""
    command = [python_executable, "scripts/run_strategy_batch.py"]
    if push:
        command.append("--push")
    return command

def build_research_monitor_command(python_executable: str = sys.executable, push: bool = False) -> list[str]:
    """构造投研机会池每日监控命令。"""
    command = [python_executable, "scripts/run_research_monitor.py"]
    if push:
        command.append("--push")
    return command


def build_live_risk_guard_command(python_executable: str = sys.executable, push: bool = False) -> list[str]:
    """构造盘后实盘风险处置命令。"""
    command = [python_executable, "scripts/run_live_risk_guard.py"]
    if push:
        command.append("--push")
    return command


def build_pre_market_check_command(python_executable: str = sys.executable, push: bool = False) -> list[str]:
    """构造开盘前风险复核命令。"""
    command = [python_executable, "scripts/run_pre_market_check.py"]
    if push:
        command.append("--push")
    return command


def build_market_open_paper_execution_command(python_executable: str = sys.executable, push: bool = False) -> list[str]:
    """构造开盘后 Paper Broker 模拟撮合命令。"""
    command = [python_executable, "scripts/run_market_open_paper_execution.py"]
    if push:
        command.append("--push")
    return command


def build_scheduler_watchdog_command(python_executable: str = sys.executable, push: bool = False) -> list[str]:
    """构造调度稳定性巡检命令。"""
    command = [python_executable, "scripts/run_scheduler_watchdog.py"]
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
    """登记每日盘后交易原子流水线任务。"""
    runtime_paths = paths or get_runtime_paths()
    command = build_daily_pipeline_command(skip_update=skip_update, push=push)
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id=TRADING_PIPELINE_JOB_ID,
        replace_existing=True,
        misfire_grace_time=DEFAULT_MISFIRE_GRACE_SECONDS,
        kwargs={
            "command": command,
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        },
    )


def install_pre_market_check_job(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    hour: int = DEFAULT_PRE_MARKET_HOUR,
    minute: int = DEFAULT_PRE_MARKET_MINUTE,
    push: bool = False,
) -> Job:
    """登记开盘前风险复核任务，仅在存在昨日风险单时通知。"""
    runtime_paths = paths or get_runtime_paths()
    command = build_pre_market_check_command(push=push)
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id=PRE_MARKET_CHECK_JOB_ID,
        replace_existing=True,
        misfire_grace_time=DEFAULT_MISFIRE_GRACE_SECONDS,
        kwargs={
            "command": command,
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        },
    )


def install_market_open_paper_execution_job(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    hour: int = DEFAULT_MARKET_OPEN_EXECUTION_HOUR,
    minute: int = DEFAULT_MARKET_OPEN_EXECUTION_MINUTE,
    push: bool = False,
) -> Job:
    """登记开盘后本地 Paper Broker 撮合任务。"""
    runtime_paths = paths or get_runtime_paths()
    command = build_market_open_paper_execution_command(push=push)
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id=MARKET_OPEN_PAPER_EXECUTION_JOB_ID,
        replace_existing=True,
        misfire_grace_time=DEFAULT_MISFIRE_GRACE_SECONDS,
        kwargs={
            "command": command,
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        },
    )


def install_live_risk_guard_job(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    push: bool = False,
) -> Job:
    """登记盘后风险处置任务，有风险动作才 Bark。"""
    runtime_paths = paths or get_runtime_paths()
    command = build_live_risk_guard_command(push=push)
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id=LIVE_RISK_GUARD_JOB_ID,
        replace_existing=True,
        misfire_grace_time=DEFAULT_MISFIRE_GRACE_SECONDS,
        kwargs={
            "command": command,
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        },
    )


def install_research_monitor_job(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    push: bool = False,
) -> Job:
    """登记投研机会池每日监控任务，保持和交易策略隔离。"""
    runtime_paths = paths or get_runtime_paths()
    command = build_research_monitor_command(push=push)
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id=RESEARCH_MONITOR_JOB_ID,
        replace_existing=True,
        misfire_grace_time=DEFAULT_MISFIRE_GRACE_SECONDS,
        kwargs={
            "command": command,
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        },
    )


def install_scheduler_watchdog_job(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    push: bool = False,
) -> Job:
    """登记调度稳定性巡检任务，正常不通知，异常才 Bark。"""
    runtime_paths = paths or get_runtime_paths()
    command = build_scheduler_watchdog_command(push=push)
    return scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id=SCHEDULER_WATCHDOG_JOB_ID,
        replace_existing=True,
        misfire_grace_time=DEFAULT_MISFIRE_GRACE_SECONDS,
        kwargs={
            "command": command,
            "cwd": str(project_root()),
            "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        },
    )


def install_daily_pipeline_jobs(
    scheduler: BackgroundScheduler,
    paths: RuntimePaths | None = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    skip_update: bool = False,
    push: bool = False,
) -> list[Job]:
    """登记所有每日盘后任务，统一由本地调度器托管。"""
    runtime_paths = paths or get_runtime_paths()
    research_hour, research_minute = _add_minutes(hour, minute, DEFAULT_RESEARCH_DELAY_MINUTES)
    risk_hour, risk_minute = _add_minutes(hour, minute, DEFAULT_LIVE_RISK_DELAY_MINUTES)
    watchdog_hour, watchdog_minute = _add_minutes(hour, minute, DEFAULT_WATCHDOG_DELAY_MINUTES)
    _remove_legacy_strategy_jobs(scheduler)
    return [
        install_pre_market_check_job(
            scheduler,
            runtime_paths,
            push=push,
        ),
        install_market_open_paper_execution_job(
            scheduler,
            runtime_paths,
            push=push,
        ),
        install_daily_pipeline_job(
            scheduler,
            runtime_paths,
            hour=hour,
            minute=minute,
            skip_update=skip_update,
            push=push,
        ),
        install_research_monitor_job(
            scheduler,
            runtime_paths,
            hour=research_hour,
            minute=research_minute,
            push=push,
        ),
        install_live_risk_guard_job(
            scheduler,
            runtime_paths,
            hour=risk_hour,
            minute=risk_minute,
            push=push,
        ),
        install_scheduler_watchdog_job(
            scheduler,
            runtime_paths,
            hour=watchdog_hour,
            minute=watchdog_minute,
            push=push,
        ),
    ]


def load_scheduler_status(paths: RuntimePaths | None = None) -> dict[str, object]:
    """读取每日调度状态，不执行流水线。"""
    runtime_paths = paths or get_runtime_paths()
    schedule = f"mon-fri {DEFAULT_HOUR:02d}:{DEFAULT_MINUTE:02d} Asia/Shanghai"
    start_hour = DEFAULT_HOUR
    start_minute = DEFAULT_MINUTE
    start_flags = ""
    jobs = _load_persisted_jobs(runtime_paths)
    job = next((item for item in jobs if item.id == TRADING_PIPELINE_JOB_ID), None)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    if job is not None:
        schedule = _describe_cron_schedule(job)
        start_hour, start_minute = _cron_hour_minute(job)
        start_flags = _start_flags_from_job(job)
    return {
        "enabled": job is not None,
        "job_id": TRADING_PIPELINE_JOB_ID,
        "job_store_path": str(runtime_paths.scheduler_state_path),
        "job_store_exists": runtime_paths.scheduler_state_path.exists(),
        "next_run_time": next_run,
        "schedule": schedule,
        "start_command": (
            f"{sys.executable} scripts/run_local_scheduler.py --hour {start_hour} --minute {start_minute}{start_flags}"
        ),
        "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        "jobs": [_job_status(item) for item in _ordered_daily_jobs(jobs)],
    }


def _load_persisted_jobs(paths: RuntimePaths) -> list[Job]:
    """直接读取 APScheduler SQLite job store，避免状态查询启动执行器。"""
    if not paths.scheduler_state_path.exists():
        return []
    with sqlite3.connect(paths.scheduler_state_path) as con:
        rows = con.execute("SELECT job_state FROM apscheduler_jobs").fetchall()
    jobs: list[Job] = []
    for (blob,) in rows:
        try:
            state = pickle.loads(blob)
            jobs.append(Job.__new__(Job))
            jobs[-1].__setstate__(state)
        except Exception:
            continue
    return jobs


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
        install_daily_pipeline_jobs(
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


def write_scheduler_heartbeat(paths: RuntimePaths | None = None) -> None:
    """写入调度器进程心跳，供本地服务巡检判断进程是否存活。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    runtime_paths.scheduler_heartbeat_path.write_text(
        f"{datetime.now().isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )


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


def _job_status(job: Job) -> dict[str, object]:
    """把 APScheduler job 转成设置页可展示的稳定结构。"""
    return {
        "job_id": job.id,
        "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        "schedule": _describe_cron_schedule(job),
        "command": job.kwargs.get("command", []),
    }


def _ordered_daily_jobs(jobs: list[Job]) -> list[Job]:
    """按页面观测优先级排序每日任务。"""
    order = {
        PRE_MARKET_CHECK_JOB_ID: 0,
        MARKET_OPEN_PAPER_EXECUTION_JOB_ID: 1,
        TRADING_PIPELINE_JOB_ID: 2,
        DATA_UPDATE_JOB_ID: 3,
        STRATEGY_BATCH_JOB_ID: 4,
        RESEARCH_MONITOR_JOB_ID: 5,
        LIVE_RISK_GUARD_JOB_ID: 6,
        SCHEDULER_WATCHDOG_JOB_ID: 7,
        DAILY_PIPELINE_JOB_ID: 7,
        "mainline_chain_daily_pipeline": 7,
    }
    return sorted(jobs, key=lambda value: (order.get(value.id, 99), value.id))


def _remove_legacy_strategy_jobs(scheduler: BackgroundScheduler) -> None:
    """迁移到策略实例批处理后，清理旧的单策略定时任务，避免重复运行。"""
    for job_id in [DATA_UPDATE_JOB_ID, STRATEGY_BATCH_JOB_ID, DAILY_PIPELINE_JOB_ID, "mainline_chain_daily_pipeline"]:
        if scheduler.get_job(job_id) is not None:
            scheduler.remove_job(job_id)


def _add_minutes(hour: int, minute: int, delta: int) -> tuple[int, int]:
    """在当天时间上增加分钟数，避免策略与数据更新同时启动。"""
    total = (hour * 60 + minute + delta) % (24 * 60)
    return total // 60, total % 60


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
