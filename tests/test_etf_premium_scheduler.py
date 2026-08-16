"""ETF 折溢价监控调度登记测试。"""

from pathlib import Path

from runtime.etf_premium_scheduler import (
    ETF_PREMIUM_MONITOR_JOB_ID,
    build_etf_premium_monitor_command,
    install_etf_premium_monitor_job,
    install_etf_premium_monitor_jobs,
)
from runtime.paths import RuntimePaths
from runtime.scheduler import create_scheduler


def test_monitor_command_is_read_only_and_can_push() -> None:
    command = build_etf_premium_monitor_command("python-test", push=True)
    assert command == [
        "python-test",
        "scripts/run_etf_premium_monitor.py",
        "--config",
        "config/etf_monitors/513500.json",
        "--push",
    ]
    assert all("pipeline" not in item.lower() for item in command)


def test_monitor_job_runs_every_five_minutes_on_weekdays(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)
    job = install_etf_premium_monitor_job(scheduler, paths, push=True)
    scheduler.start(paused=True)
    try:
        registered = scheduler.get_job(ETF_PREMIUM_MONITOR_JOB_ID)
    finally:
        scheduler.shutdown()

    assert registered is not None
    assert job.id == ETF_PREMIUM_MONITOR_JOB_ID
    assert "day_of_week='mon-fri'" in str(job.trigger)
    assert "minute='*/5'" in str(job.trigger)
    assert job.kwargs["log_path"].endswith("logs/etf_premium_monitor_513500.log")
    assert "--push" in job.kwargs["command"]


def test_allocation_monitors_register_gold_and_bond_without_pipeline(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)
    jobs = install_etf_premium_monitor_jobs(scheduler, paths, push=True)
    scheduler.start(paused=True)
    try:
        registered = {job.id: job for job in scheduler.get_jobs()}
    finally:
        scheduler.shutdown()

    assert set(registered) == {
        "etf_513500_premium_monitor",
        "etf_518880_allocation_monitor",
        "etf_511010_allocation_monitor",
    }
    assert "config/etf_monitors/518880.json" in registered["etf_518880_allocation_monitor"].kwargs["command"]
    assert "config/etf_monitors/511010.json" in registered["etf_511010_allocation_monitor"].kwargs["command"]
    assert all(
        "pipeline" not in item.lower()
        for job in jobs
        for item in job.kwargs["command"]
    )
