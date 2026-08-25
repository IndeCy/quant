from runtime.paths import RuntimePaths
from runtime.portfolio_rebalance_scheduler import (
    PORTFOLIO_REBALANCE_JOB_ID,
    build_portfolio_rebalance_command,
    install_portfolio_rebalance_job,
)
from runtime.scheduler import create_scheduler


def test_rebalance_command_is_notification_only() -> None:
    command = build_portfolio_rebalance_command("python-test", push=True)

    assert command == [
        "python-test",
        "scripts/run_portfolio_rebalance_monitor.py",
        "--config",
        "config/portfolio_rebalance.json",
        "--push",
    ]
    assert all("daily_pipeline" not in item for item in command)


def test_rebalance_job_runs_once_before_market(tmp_path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    scheduler = create_scheduler(paths)
    job = install_portfolio_rebalance_job(scheduler, paths, push=True)
    scheduler.start(paused=True)
    try:
        registered = scheduler.get_job(PORTFOLIO_REBALANCE_JOB_ID)
    finally:
        scheduler.shutdown()

    assert registered is not None
    assert job.id == PORTFOLIO_REBALANCE_JOB_ID
    assert "hour='9'" in str(job.trigger)
    assert "minute='25'" in str(job.trigger)
    assert "--push" in job.kwargs["command"]
    assert job.kwargs["log_path"].endswith("logs/portfolio_rebalance_monitor.log")
