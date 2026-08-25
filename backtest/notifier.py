"""
系统通知模块

提供统一通知接口，当前支持 Bark 手机推送。
后续如需接入邮件、PushPlus、Server酱，可以在这里新增 provider。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote
from urllib.request import urlopen


@dataclass(frozen=True)
class NotificationMessage:
    """系统通知消息。"""

    title: str
    body: str


class Notifier(Protocol):
    """通知器协议，所有渠道都实现 send。"""

    def send(self, message: NotificationMessage) -> None:
        """发送通知消息。"""


class BarkNotifier:
    """Bark 手机通知器。"""

    def __init__(self, endpoint: str):
        if not endpoint:
            raise ValueError("Bark endpoint 不能为空")
        self.endpoint = endpoint.rstrip("/")

    def build_url(self, message: NotificationMessage) -> str:
        """构造 Bark 推送 URL，标题和正文必须编码。"""
        title = quote(message.title, safe="")
        body = quote(message.body, safe="")
        return f"{self.endpoint}/{title}/{body}"

    def send(self, message: NotificationMessage) -> None:
        """通过 Bark API 发送手机通知。"""
        with urlopen(self.build_url(message), timeout=10) as response:
            response.read()


def build_notifier(provider: str, endpoint: str) -> Notifier:
    """按 provider 创建通知器。"""
    normalized = provider.lower().strip()
    if normalized == "bark":
        return BarkNotifier(endpoint)
    raise ValueError(f"暂不支持的通知渠道: {provider}")
