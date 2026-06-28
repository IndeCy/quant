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
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """返回本地运行目录健康状态。"""
        return api_service.health()

    @app.get("/api/scheduler/status")
    def scheduler_status() -> dict[str, Any]:
        """返回每日自动运行调度状态。"""
        return api_service.scheduler_status()

    @app.post("/api/scheduler/daily-job")
    def configure_scheduler_job(payload: dict[str, Any]) -> dict[str, Any]:
        """登记每日自动运行任务，不立即执行策略。"""
        try:
            return api_service.configure_scheduler_job(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/backup/manifest")
    def backup_manifest() -> dict[str, Any]:
        """返回运行目录备份和迁移清单。"""
        return api_service.backup_manifest()

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

    @app.get("/api/factors/{factor_id}")
    def factor_detail(factor_id: str) -> dict[str, Any]:
        """返回因子定义和使用该因子的策略。"""
        detail = api_service.factor_detail(factor_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="factor not found")
        return detail

    @app.get("/api/strategy-drafts")
    def strategy_drafts() -> list[dict[str, Any]]:
        """返回本地策略草案列表。"""
        return api_service.strategy_drafts()

    @app.get("/api/strategy-drafts/{draft_id}")
    def strategy_draft_detail(draft_id: str) -> dict[str, Any]:
        """返回本地策略草案详情。"""
        detail = api_service.strategy_draft_detail(draft_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="strategy draft not found")
        return detail

    @app.post("/api/strategy-drafts")
    def save_strategy_draft(payload: dict[str, Any]) -> dict[str, Any]:
        """保存本地策略草案。"""
        try:
            return api_service.save_strategy_draft(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
