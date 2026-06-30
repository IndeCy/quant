"""运行系统通知配置。"""

from __future__ import annotations

import os


BARK_ENV_KEYS = ("BARK_PUSH_URL", "BARK_URL", "QUANT_BARK_URL")


def resolve_bark_url() -> str:
    """按统一优先级读取 Bark 推送地址。"""
    for key in BARK_ENV_KEYS:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""
