"""运行系统通知配置。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import plistlib

from backtest.notifier import NotificationMessage, build_notifier


BARK_ENV_KEYS = ("BARK_PUSH_URL", "BARK_URL", "QUANT_BARK_URL")
SCHEDULER_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.quant.scheduler.plist"


@dataclass(frozen=True)
class NotificationResult:
    """通知发送结果，用于写入流水线排查日志。"""

    status: str
    message: str


def resolve_bark_url() -> str:
    """按统一优先级读取 Bark 推送地址。"""
    for key in BARK_ENV_KEYS:
        value = os.getenv(key, "").strip()
        if value:
            return value
    value = _read_bark_url_from_launchd(SCHEDULER_PLIST_PATH)
    if value:
        return value
    return ""


def send_bark_notification(title: str, body: str, bark_url: str | None = None) -> NotificationResult:
    """发送 Bark 通知，并返回可落库的状态，不再静默吞掉失败。"""
    endpoint = (bark_url if bark_url is not None else resolve_bark_url()).strip()
    if not endpoint:
        return NotificationResult("SKIPPED", "Bark未配置: BARK_PUSH_URL/BARK_URL/QUANT_BARK_URL均为空")
    try:
        build_notifier("bark", endpoint).send(NotificationMessage(title=title, body=body))
    except Exception as exc:
        return NotificationResult("FAILED", f"Bark发送失败: {exc}")
    return NotificationResult("SUCCESS", "Bark通知已发送")


def _read_bark_url_from_launchd(path: Path) -> str:
    """从已安装的本机调度器 plist 读取 Bark 配置，保证手动补跑复用同一配置。"""
    if not path.exists():
        return ""
    try:
        with path.open("rb") as file:
            payload = plistlib.load(file)
    except Exception:
        return ""
    env = payload.get("EnvironmentVariables", {})
    if not isinstance(env, dict):
        return ""
    for key in BARK_ENV_KEYS:
        value = str(env.get(key, "")).strip()
        if value:
            return value
    return ""
