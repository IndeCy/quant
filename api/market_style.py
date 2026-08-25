"""大小盘风格观测 API 助手。"""

from __future__ import annotations

from typing import Any

from data.market_style_view import load_market_style_overview
from runtime.paths import RuntimePaths


def market_style_overview(paths: RuntimePaths, limit: int = 240) -> dict[str, Any]:
    """从标准基准缓存读取大小盘风格视图。"""
    return load_market_style_overview(paths.benchmark_increment_path, limit=limit)
