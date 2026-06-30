"""本地调度器测试。"""

from pathlib import Path
import sys

from runtime.paths import RuntimePaths
from runtime.scheduler import (
    build_strategy_batch_command,
    build_daily_data_update_command,
    build_daily_pipeline_command,
    build_mainline_chain_daily_command,
    create_scheduler,
    install_daily_pipeline_job,
    install_daily_pipeline_jobs,
    install_mainline_chain_daily_job,
    load_scheduler_status,
)


def test_build_daily_pipeline_command_uses_existing_script(tmp_path: Path) -> None:
    """调度器应复用既有每日流水线脚本，不复制策略逻辑。"""
    command = build_daily_pipeline_command("python-test", skip_update=True, push=False)

    assert command[:2] == ["python-test", "examples/run_quality_overlay_paper.py"]
    assert "--skip-update" in command
    assert "--push" not in command


def test_build_daily_data_update_command_uses_dedicated_script(tmp_path: Path) -> None:
    """数据更新应从策略执行中拆出，成为独立前置任务。"""
    command = build_daily_data_update_command("python-test")

    assert command == ["python-test", "scripts/run_daily_data_update.py"]


def test_build_mainline_chain_daily_command_uses_wrapper_script(tmp_path: Path) -> None:
    """主线链动调度应使用盘后观察和监控同步包装脚本。"""
    command = build_mainline_chain_daily_command("python-test", push=True)

    assert command == ["python-test", "scripts/run_mainline_chain_daily.py", "--push"]


def test_build_strategy_batch_command_uses_dynamic_runner(tmp_path: Path) -> None:
    """策略调度应运行动态批量入口，而不是为每个策略写固定 job。"""
    command = build_strategy_batch_command("python-test")

    assert command == ["python-test", "scripts/run_strategy_batch.py"]


def test_build_strategy_batch_command_can_enable_push(tmp_path: Path) -> None:
    """调度器开启通知时，策略批处理入口应收到 push 标记。"""
    command = build_strategy_batch_command("python-test", push=True)

    assert command == ["python-test", "scripts/run_strategy_batch.py", "--push"]


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


def test_install_daily_pipeline_jobs_registers_data_then_batch_runner(tmp_path: Path) -> None:
    """每日调度应先更新数据，再运行策略实例批量任务。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)

    jobs = install_daily_pipeline_jobs(scheduler, paths, hour=16, minute=10, skip_update=True, push=True)

    assert [job.id for job in jobs] == [
        "daily_data_update_pipeline",
        "strategy_batch_pipeline",
    ]
    assert jobs[0].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_daily_data_update.py",
    ]
    assert jobs[1].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_strategy_batch.py",
    ]
    assert "--push" in jobs[1].kwargs["command"]
    assert jobs[1].kwargs["log_path"].endswith("logs/scheduler.log")


def test_install_daily_pipeline_jobs_removes_legacy_strategy_jobs(tmp_path: Path) -> None:
    """迁移到动态批处理后，应删除旧单策略任务，避免每日重复运行。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)
    install_daily_pipeline_job(scheduler, paths, hour=16, minute=10, skip_update=True)

    install_mainline_chain_daily_job(scheduler, paths, hour=16, minute=10)

    install_daily_pipeline_jobs(scheduler, paths, hour=16, minute=10, skip_update=True, push=True)

    assert scheduler.get_job("quality_overlay_daily_pipeline") is None
    assert scheduler.get_job("mainline_chain_daily_pipeline") is None
    assert scheduler.get_job("strategy_batch_pipeline") is not None


def test_load_scheduler_status_reports_registered_daily_job(tmp_path: Path) -> None:
    """调度状态应可被 API 和前端读取，并列出所有每日任务。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)
    install_daily_pipeline_jobs(scheduler, paths, hour=16, minute=10, skip_update=True, push=True)
    scheduler.start(paused=True)
    try:
        status = load_scheduler_status(paths)
    finally:
        scheduler.shutdown()

    assert status["enabled"] is True
    assert status["job_id"] == "strategy_batch_pipeline"
    assert status["job_store_exists"] is True
    assert status["schedule"] == "mon-fri 16:10 Asia/Shanghai"
    assert "T16:10:00" in str(status["next_run_time"])
    assert "scripts/run_local_scheduler.py" in status["start_command"]
    assert "--push" in status["start_command"]
    assert [item["job_id"] for item in status["jobs"]] == [
        "daily_data_update_pipeline",
        "strategy_batch_pipeline",
    ]
    assert status["jobs"][0]["schedule"] == "mon-fri 16:10 Asia/Shanghai"
    assert status["jobs"][1]["schedule"] == "mon-fri 16:20 Asia/Shanghai"
