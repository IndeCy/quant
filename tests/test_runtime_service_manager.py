"""本地服务管理器测试。"""

from pathlib import Path

from runtime.paths import RuntimePaths
from runtime.scheduler import configure_daily_pipeline_job
from runtime.service_manager import build_launchd_plist, build_service_commands, build_service_status


def test_build_service_commands_describes_local_processes(tmp_path: Path) -> None:
    """服务管理信息应覆盖 API、前端和调度器三个本地进程。"""
    paths = RuntimePaths(tmp_path / "runtime")
    commands = build_service_commands(paths, python_executable="python-test")

    names = [item["name"] for item in commands]
    assert names == ["api", "frontend", "scheduler"]
    assert commands[0]["command"][:3] == ["python-test", "-m", "api.local_server"]
    assert commands[1]["command"][:3] == ["python-test", "-m", "runtime.static_frontend_server"]
    assert commands[1]["command"][-2:] == ["--port", "5173"]
    assert commands[2]["command"][1] == "scripts/run_local_scheduler.py"
    assert "--push" in commands[2]["command"]


def test_build_launchd_plist_contains_quant_home_and_command(tmp_path: Path) -> None:
    """launchd plist 只生成文本，便于用户确认后安装。"""
    paths = RuntimePaths(tmp_path / "runtime")
    plist = build_launchd_plist(
        label="com.quant.api",
        command=["python-test", "-m", "api.local_server"],
        cwd="/tmp/quant",
        log_path=str(paths.logs_dir / "api.log"),
        quant_home=str(paths.root),
    )

    assert "<key>Label</key>" in plist
    assert "<string>com.quant.api</string>" in plist
    assert "<key>QUANT_HOME</key>" in plist
    assert "<string>python-test</string>" in plist


def test_build_service_status_reports_configured_checks(tmp_path: Path) -> None:
    """服务状态巡检应覆盖端口服务和调度器进程。"""
    paths = RuntimePaths(tmp_path / "runtime")
    configure_daily_pipeline_job(paths)
    status = build_service_status(paths)

    names = [item["name"] for item in status["services"]]
    assert names == ["api", "frontend", "scheduler"]
    assert status["services"][0]["check"] == "tcp:127.0.0.1:8765"
    assert status["services"][1]["check"] == "tcp:127.0.0.1:5173"
    assert status["services"][2]["check"] == "heartbeat:scheduler"
    assert status["services"][2]["running"] is False


def test_build_service_status_marks_scheduler_running_only_with_fresh_heartbeat(tmp_path: Path) -> None:
    """仅登记任务不代表调度器进程存活，必须有新鲜 heartbeat。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    paths.scheduler_heartbeat_path.write_text("2026-06-29T16:00:00+08:00\n", encoding="utf-8")

    status = build_service_status(paths)

    assert status["services"][2]["running"] is True
