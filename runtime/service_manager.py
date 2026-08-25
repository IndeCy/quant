"""本地服务启动信息生成器。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import socket
import sys
from typing import Any
import xml.sax.saxutils

from runtime.paths import RuntimePaths, get_runtime_paths


def project_root() -> Path:
    """定位项目根目录。"""
    return Path(__file__).resolve().parents[1]


def build_service_commands(
    paths: RuntimePaths | None = None,
    python_executable: str = sys.executable,
) -> list[dict[str, Any]]:
    """生成本地三类常驻进程的启动命令，运行时不依赖 Vite。"""
    runtime_paths = paths or get_runtime_paths()
    root = project_root()
    return [
        {
            "name": "api",
            "label": "com.quant.api",
            "cwd": str(root),
            "command": [python_executable, "-m", "api.local_server", "--host", "127.0.0.1", "--port", "8765"],
            "log_path": str(runtime_paths.logs_dir / "api.log"),
        },
        {
            "name": "frontend",
            "label": "com.quant.frontend",
            "cwd": str(root),
            "command": [
                python_executable,
                "-m",
                "runtime.static_frontend_server",
                "--directory",
                str(root / "frontend" / "dist"),
                "--port",
                "5173",
            ],
            "log_path": str(runtime_paths.logs_dir / "frontend.log"),
        },
        {
            "name": "scheduler",
            "label": "com.quant.scheduler",
            "cwd": str(root),
            "command": [python_executable, "scripts/run_local_scheduler.py", "--hour", "16", "--minute", "30", "--push"],
            "log_path": str(runtime_paths.logs_dir / "scheduler.log"),
        },
    ]


def build_launchd_plist(
    label: str,
    command: list[str],
    cwd: str,
    log_path: str,
    quant_home: str,
) -> str:
    """生成 macOS launchd plist 文本，调用方自行确认后安装。"""
    args = "\n".join(f"    <string>{_escape(item)}</string>" for item in command)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{_escape(label)}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>WorkingDirectory</key>
  <string>{_escape(cwd)}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>QUANT_HOME</key>
    <string>{_escape(quant_home)}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{_escape(log_path)}</string>
  <key>StandardErrorPath</key>
  <string>{_escape(log_path)}</string>
</dict>
</plist>
"""


def build_service_manifest(paths: RuntimePaths | None = None) -> dict[str, Any]:
    """生成前端可展示的服务命令和 launchd 模板。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    services = []
    for item in build_service_commands(runtime_paths):
        services.append(
            {
                **item,
                "launchd_plist": build_launchd_plist(
                    label=str(item["label"]),
                    command=list(item["command"]),
                    cwd=str(item["cwd"]),
                    log_path=str(item["log_path"]),
                    quant_home=str(runtime_paths.root),
                ),
            }
        )
    return {"runtime_root": str(runtime_paths.root), "services": services}


def build_service_status(paths: RuntimePaths | None = None) -> dict[str, Any]:
    """巡检本地 API、前端和调度器进程状态。"""
    runtime_paths = paths or get_runtime_paths()
    return {
        "runtime_root": str(runtime_paths.root),
        "services": [
            {
                "name": "api",
                "check": "tcp:127.0.0.1:8765",
                "running": _is_tcp_open("127.0.0.1", 8765),
            },
            {
                "name": "frontend",
                "check": "tcp:127.0.0.1:5173",
                "running": _is_tcp_open("127.0.0.1", 5173),
            },
            {
                "name": "scheduler",
                "check": "heartbeat:scheduler",
                "running": _is_fresh_file(runtime_paths.scheduler_heartbeat_path),
            },
        ],
    }


def _escape(value: str) -> str:
    return xml.sax.saxutils.escape(value, {'"': "&quot;"})


def _is_tcp_open(host: str, port: int) -> bool:
    """检查本机端口是否可连接。"""
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _is_fresh_file(path: Path, max_age_seconds: int = 180) -> bool:
    """检查 heartbeat 文件是否仍然新鲜。"""
    if not path.exists():
        return False
    modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    age = (datetime.now() - modified_at).total_seconds()
    return age <= max_age_seconds
