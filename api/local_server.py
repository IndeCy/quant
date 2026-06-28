"""FastAPI 本地 API server。"""

from __future__ import annotations

import argparse
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.service import LocalApiService


def create_app(service: LocalApiService | None = None) -> FastAPI:
    """创建本地量化系统 API 应用。"""
    api_service = service or LocalApiService()
    app = FastAPI(title="Quant Local API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """返回本地运行目录健康状态。"""
        return api_service.health()

    @app.get("/api/strategies")
    def strategies() -> list[dict[str, Any]]:
        """返回策略列表。"""
        return api_service.strategies()

    @app.get("/api/strategies/{strategy_id}")
    def strategy_detail(strategy_id: str) -> dict[str, Any]:
        """返回策略定义、最新运行和最新指标。"""
        detail = api_service.strategy_detail(strategy_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="strategy not found")
        return detail

    @app.get("/api/factors")
    def factors() -> list[dict[str, Any]]:
        """返回因子列表。"""
        return api_service.factors()

    @app.get("/api/data/health")
    def data_health() -> dict[str, Any]:
        """返回本地数据健康状态。"""
        return api_service.data_health()

    @app.get("/api/reports")
    def reports(strategy_id: str | None = None) -> list[dict[str, Any]]:
        """返回报告索引。"""
        return api_service.reports(strategy_id)

    @app.get("/api/reports/{report_id}")
    def report_content(report_id: str) -> dict[str, Any]:
        """返回报告文件内容。"""
        content = api_service.report_content(report_id)
        if content is None:
            raise HTTPException(status_code=404, detail="report not found")
        return content

    @app.get("/api/runs")
    def runs(strategy_id: str | None = None, limit: int = Query(default=30, ge=1, le=500)) -> list[dict[str, Any]]:
        """返回运行记录。"""
        return api_service.runs(strategy_id=strategy_id, limit=limit)

    @app.get("/api/runs/{strategy_id}/{trade_date}")
    def run_detail(strategy_id: str, trade_date: str) -> dict[str, Any]:
        """返回某次运行详情。"""
        detail = api_service.run_detail(strategy_id, trade_date)
        if detail is None:
            raise HTTPException(status_code=404, detail="run not found")
        return detail

    @app.get("/api/series/strategy/{strategy_id}")
    def strategy_series(strategy_id: str) -> list[dict[str, Any]]:
        """返回策略指标曲线。"""
        return api_service.strategy_series(strategy_id)

    @app.get("/api/series/market/{benchmark_id}")
    def market_series(benchmark_id: str) -> list[dict[str, Any]]:
        """返回市场基准曲线。"""
        return api_service.market_series(benchmark_id)

    return app


def main() -> None:
    """启动本地 FastAPI 服务。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
