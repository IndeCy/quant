"""本地调度器测试。"""

from pathlib import Path
import sys

from runtime.paths import RuntimePaths
from runtime.scheduler import (
    MARKET_OPEN_PAPER_EXECUTION_JOB_ID,
    TRADING_PIPELINE_JOB_ID,
    build_market_open_paper_execution_command,
    build_live_risk_guard_command,
    build_pre_market_check_command,
    build_research_monitor_command,
    build_scheduler_watchdog_command,
    build_strategy_batch_command,
    build_daily_data_update_command,
    build_daily_pipeline_command,
    create_scheduler,
    install_daily_pipeline_job,
    install_daily_pipeline_jobs,
    load_scheduler_status,
    run_daily_pipeline,
)


def test_build_daily_pipeline_command_uses_existing_script(tmp_path: Path) -> None:
    """调度器应复用唯一每日交易流水线脚本，不复制策略逻辑。"""
    command = build_daily_pipeline_command("python-test", skip_update=True, push=False)

    assert command == ["python-test", "scripts/run_daily_pipeline.py", "--source", "scheduler"]
    assert "--skip-update" not in command
    assert "--push" not in command


def test_build_daily_data_update_command_uses_dedicated_script(tmp_path: Path) -> None:
    """数据更新应从策略执行中拆出，成为独立前置任务。"""
    command = build_daily_data_update_command("python-test")

    assert command == ["python-test", "scripts/run_daily_data_update.py"]


def test_build_strategy_batch_command_uses_dynamic_runner(tmp_path: Path) -> None:
    """策略调度应运行动态批量入口，而不是为每个策略写固定 job。"""
    command = build_strategy_batch_command("python-test")

    assert command == ["python-test", "scripts/run_strategy_batch.py"]


def test_build_strategy_batch_command_can_enable_push(tmp_path: Path) -> None:
    """调度器开启通知时，策略批处理入口应收到 push 标记。"""
    command = build_strategy_batch_command("python-test", push=True)

    assert command == ["python-test", "scripts/run_strategy_batch.py", "--push"]


def test_build_research_monitor_command_uses_opportunity_runner(tmp_path: Path) -> None:
    """投研观察池应有独立入口，不能混入交易策略批处理。"""
    command = build_research_monitor_command("python-test")

    assert command == ["python-test", "scripts/run_research_monitor.py"]


def test_install_daily_pipeline_job_registers_quality_cron_job(tmp_path: Path) -> None:
    """APScheduler 中应登记唯一每日交易流水线任务。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)

    job = install_daily_pipeline_job(scheduler, paths, hour=16, minute=10, skip_update=True)
    scheduler.start(paused=True)
    try:
        registered = scheduler.get_job(TRADING_PIPELINE_JOB_ID)
    finally:
        scheduler.shutdown()

    assert job.id == TRADING_PIPELINE_JOB_ID
    assert job.kwargs["cwd"].endswith("quant")
    assert job.kwargs["log_path"].endswith("logs/scheduler.log")
    assert job.kwargs["command"][:2] == [sys.executable, "scripts/run_daily_pipeline.py"]
    assert registered is not None
    assert registered.misfire_grace_time >= 900


def test_install_daily_pipeline_jobs_registers_data_then_batch_runner(tmp_path: Path) -> None:
    """每日调度应把交易流程收敛为一个原子任务，投研监控独立。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)

    jobs = install_daily_pipeline_jobs(scheduler, paths, hour=16, minute=10, skip_update=True, push=True)
    scheduler.start(paused=True)
    try:
        registered_jobs = scheduler.get_jobs()
    finally:
        scheduler.shutdown()

    assert [job.id for job in jobs] == [
        "pre_market_check_pipeline",
        "market_open_paper_execution_pipeline",
        "daily_trading_pipeline",
        "research_monitor_pipeline",
        "live_risk_guard_pipeline",
        "scheduler_watchdog_pipeline",
    ]
    assert jobs[0].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_pre_market_check.py",
    ]
    assert "--push" in jobs[0].kwargs["command"]
    assert jobs[1].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_market_open_paper_execution.py",
    ]
    assert "--push" in jobs[1].kwargs["command"]
    assert jobs[2].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_daily_pipeline.py",
    ]
    assert "--push" in jobs[2].kwargs["command"]
    assert jobs[2].kwargs["log_path"].endswith("logs/scheduler.log")
    assert jobs[3].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_research_monitor.py",
    ]
    assert "--push" in jobs[3].kwargs["command"]
    assert jobs[4].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_live_risk_guard.py",
    ]
    assert "--push" in jobs[4].kwargs["command"]
    assert jobs[5].kwargs["command"][:2] == [
        sys.executable,
        "scripts/run_scheduler_watchdog.py",
    ]
    assert "--push" in jobs[5].kwargs["command"]
    assert all(job.misfire_grace_time >= 900 for job in registered_jobs)


def test_install_daily_pipeline_jobs_removes_legacy_strategy_jobs(tmp_path: Path) -> None:
    """迁移到动态批处理后，应删除旧单策略任务，避免每日重复运行。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)
    install_daily_pipeline_job(scheduler, paths, hour=16, minute=10, skip_update=True)

    scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        day_of_week="mon-fri",
        hour=16,
        minute=10,
        id="mainline_chain_daily_pipeline",
        replace_existing=True,
        kwargs={"command": ["python-test", "old.py"], "cwd": str(tmp_path), "log_path": str(tmp_path / "old.log")},
    )

    install_daily_pipeline_jobs(scheduler, paths, hour=16, minute=10, skip_update=True, push=True)

    assert scheduler.get_job("quality_overlay_daily_pipeline") is None
    assert scheduler.get_job("mainline_chain_daily_pipeline") is None
    assert scheduler.get_job("daily_data_update_pipeline") is None
    assert scheduler.get_job("strategy_batch_pipeline") is None
    assert scheduler.get_job("daily_trading_pipeline") is not None


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
    assert status["job_id"] == "daily_trading_pipeline"
    assert status["job_store_exists"] is True
    assert status["schedule"] == "mon-fri 16:10 Asia/Shanghai"
    assert "T16:10:00" in str(status["next_run_time"])
    assert "scripts/run_local_scheduler.py" in status["start_command"]
    assert "--push" in status["start_command"]
    assert [item["job_id"] for item in status["jobs"]] == [
        "pre_market_check_pipeline",
        "market_open_paper_execution_pipeline",
        "daily_trading_pipeline",
        "research_monitor_pipeline",
        "live_risk_guard_pipeline",
        "scheduler_watchdog_pipeline",
    ]
    assert status["jobs"][0]["schedule"] == "mon-fri 09:20 Asia/Shanghai"
    assert status["jobs"][1]["schedule"] == "mon-fri 09:35 Asia/Shanghai"
    assert status["jobs"][2]["schedule"] == "mon-fri 16:10 Asia/Shanghai"
    assert status["jobs"][3]["schedule"] == "mon-fri 16:25 Asia/Shanghai"
    assert status["jobs"][4]["schedule"] == "mon-fri 16:35 Asia/Shanghai"
    assert status["jobs"][5]["schedule"] == "mon-fri 16:45 Asia/Shanghai"


def test_build_scheduler_watchdog_command_can_enable_push(tmp_path: Path) -> None:
    """稳定性巡检任务异常时应具备 Bark 通知能力。"""
    command = build_scheduler_watchdog_command("python-test", push=True)

    assert command == ["python-test", "scripts/run_scheduler_watchdog.py", "--push"]


def test_build_live_risk_commands_can_enable_push(tmp_path: Path) -> None:
    """盘后风控和开盘前复核都应具备 Bark 通知能力。"""
    assert build_live_risk_guard_command("python-test", push=True) == [
        "python-test",
        "scripts/run_live_risk_guard.py",
        "--push",
    ]
    assert build_pre_market_check_command("python-test", push=True) == [
        "python-test",
        "scripts/run_pre_market_check.py",
        "--push",
    ]


def test_build_market_open_paper_execution_command_can_enable_push() -> None:
    """开盘撮合任务应具备统一 Bark 通知能力。"""
    assert MARKET_OPEN_PAPER_EXECUTION_JOB_ID == "market_open_paper_execution_pipeline"
    assert build_market_open_paper_execution_command("python-test", push=True) == [
        "python-test",
        "scripts/run_market_open_paper_execution.py",
        "--push",
    ]
