"""本地服务管理器测试。"""

from pathlib import Path

from runtime.paths import RuntimePaths
from runtime.service_manager import build_launchd_plist, build_service_commands


def test_build_service_commands_describes_local_processes(tmp_path: Path) -> None:
    """服务管理信息应覆盖 API、前端和调度器三个本地进程。"""
    paths = RuntimePaths(tmp_path / "runtime")
    commands = build_service_commands(paths, python_executable="python-test", node_executable="node-test")

    names = [item["name"] for item in commands]
    assert names == ["api", "frontend", "scheduler"]
    assert commands[0]["command"][:3] == ["python-test", "-m", "api.local_server"]
    assert commands[1]["cwd"].endswith("frontend")
    assert commands[2]["command"][1] == "scripts/run_local_scheduler.py"


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
