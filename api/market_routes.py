"""市场观测只读 API 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query

from api.market_index import market_index_comparison
from api.market_style import market_style_overview
from api.service import LocalApiService


def register_market_routes(app: FastAPI, service: LocalApiService) -> None:
    """注册市场指数与风格观测路由。"""

    @app.get("/api/market/index-comparison")
    def index_comparison(limit: int = Query(default=5000, ge=2, le=5000)) -> dict[str, Any]:
        """返回多策略净值图使用的指数、ETF与研究曲线。"""
        return market_index_comparison(service.paths, limit=limit)

    @app.get("/api/market/style-overview")
    def style_overview(limit: int = Query(default=240, ge=60, le=1000)) -> dict[str, Any]:
        """返回微盘与大盘风格代理的 K 线观测。"""
        return market_style_overview(service.paths, limit=limit)
