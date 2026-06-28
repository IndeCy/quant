"""本地调度器测试。"""

from pathlib import Path

from runtime.paths import RuntimePaths
from runtime.scheduler import (
    build_daily_pipeline_command,
    create_scheduler,
    install_daily_pipeline_job,
    load_scheduler_status,
)


def test_build_daily_pipeline_command_uses_existing_script(tmp_path: Path) -> None:
    """调度器应复用既有每日流水线脚本，不复制策略逻辑。"""
    command = build_daily_pipeline_command("python-test", skip_update=True, push=False)

    assert command[:2] == ["python-test", "examples/run_quality_overlay_paper.py"]
    assert "--skip-update" in command
    assert "--push" not in command


def test_install_daily_pipeline_job_registers_cron_job(tmp_path: Path) -> None:
    """APScheduler 中应登记每日 Quality Alpha 流水线任务。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)

    job = install_daily_pipeline_job(scheduler, paths, hour=16, minute=10, skip_update=True)

    assert job.id == "quality_overlay_daily_pipeline"
    assert job.kwargs["cwd"].endswith("quant")
    assert job.kwargs["log_path"].endswith("logs/scheduler.log")
    assert "--skip-update" in job.kwargs["command"]


def test_load_scheduler_status_reports_registered_daily_job(tmp_path: Path) -> None:
    """调度状态应可被 API 和前端读取。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)
    install_daily_pipeline_job(scheduler, paths, hour=16, minute=10, skip_update=True)
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
