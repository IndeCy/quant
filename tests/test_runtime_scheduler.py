"""本地调度器测试。"""

from pathlib import Path
import sys

from runtime.paths import RuntimePaths
from runtime.scheduler import (
    build_daily_pipeline_command,
    build_mainline_chain_daily_command,
    create_scheduler,
    install_daily_pipeline_job,
    install_daily_pipeline_jobs,
    load_scheduler_status,
)


def test_build_daily_pipeline_command_uses_existing_script(tmp_path: Path) -> None:
    """调度器应复用既有每日流水线脚本，不复制策略逻辑。"""
    command = build_daily_pipeline_command("python-test", skip_update=True, push=False)

    assert command[:2] == ["python-test", "examples/run_quality_overlay_paper.py"]
    assert "--skip-update" in command
    assert "--push" not in command


def test_build_mainline_chain_daily_command_uses_wrapper_script(tmp_path: Path) -> None:
    """主线链动调度应使用盘后观察和监控同步包装脚本。"""
    command = build_mainline_chain_daily_command("python-test", push=True)

    assert command == ["python-test", "scripts/run_mainline_chain_daily.py", "--push"]


def test_install_daily_pipeline_job_registers_quality_cron_job(tmp_path: Path) -> None:
    """APScheduler 中应登记每日 Quality Alpha 流水线任务。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)

    job = install_daily_pipeline_job(scheduler, paths, hour=16, minute=10, skip_update=True)

    assert job.id == "quality_overlay_daily_pipeline"
    assert job.kwargs["cwd"].endswith("quant")
    assert job.kwargs["log_path"].endswith("logs/scheduler.log")
    assert "--skip-update" in job.kwargs["command"]


def test_install_daily_pipeline_jobs_registers_quality_and_mainline(tmp_path: Path) -> None:
    """每日调度应同时登记 Quality 和主线链动两个观测任务。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)

    jobs = install_daily_pipeline_jobs(scheduler, paths, hour=16, minute=10, skip_update=True)

    assert [job.id for job in jobs] == [
        "quality_overlay_daily_pipeline",
        "mainline_chain_daily_pipeline",
    ]
    assert jobs[1].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_mainline_chain_daily.py",
    ]
    assert jobs[1].kwargs["log_path"].endswith("logs/scheduler.log")


def test_load_scheduler_status_reports_registered_daily_job(tmp_path: Path) -> None:
    """调度状态应可被 API 和前端读取，并列出所有每日任务。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)
    install_daily_pipeline_jobs(scheduler, paths, hour=16, minute=10, skip_update=True)
    scheduler.start(paused=True)
    try:
        status = load_scheduler_status(paths)
    finally:
        scheduler.shutdown()

    assert status["enabled"] is True
    assert status["job_id"] == "quality_overlay_daily_pipeline"
    assert status["job_store_exists"] is True
    assert status["schedule"] == "mon-fri 16:10 Asia/Shanghai"
    assert "scripts/run_local_scheduler.py" in status["start_command"]
    assert [item["job_id"] for item in status["jobs"]] == [
        "quality_overlay_daily_pipeline",
        "mainline_chain_daily_pipeline",
    ]
