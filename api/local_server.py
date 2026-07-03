"""FastAPI 本地 API server。"""

from __future__ import annotations

import argparse
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.service import LocalApiService
from runtime.environment_audit import build_environment_audit
from runtime.operations_ack import list_operations_ack, record_operations_ack
from runtime.operations_quality_report import build_operations_quality_report
from runtime.operations_review import build_operations_review


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

    @app.get("/api/readiness")
    def readiness() -> dict[str, Any]:
        """返回生产候选系统运行就绪度。"""
        return api_service.readiness()

    @app.get("/api/environment/audit")
    def environment_audit() -> dict[str, Any]:
        """返回本机进程和 launchd 关键环境变量一致性。"""
        return build_environment_audit()

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

    @app.post("/api/pipeline/daily-run")
    def run_daily_pipeline(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """手动补跑每日交易流水线，和调度器共用同一入口。"""
        return api_service.run_daily_pipeline(payload or {})

    @app.get("/api/backup/manifest")
    def backup_manifest() -> dict[str, Any]:
        """返回运行目录备份和迁移清单。"""
        return api_service.backup_manifest()

    @app.get("/api/services/manifest")
    def service_manifest() -> dict[str, Any]:
        """返回本地常驻服务启动命令和 launchd 模板。"""
        return api_service.service_manifest()

    @app.get("/api/services/status")
    def service_status() -> dict[str, Any]:
        """返回本地常驻服务巡检状态。"""
        return api_service.service_status()

    @app.get("/api/operations/observation")
    def operations_observation() -> dict[str, Any]:
        """返回长期运行观察摘要。"""
        return api_service.operations_observation()

    @app.get("/api/operations/decision")
    def operations_decision() -> dict[str, Any]:
        """返回今天是否需要人工处理的运行决策。"""
        return api_service.operations_decision()

    @app.get("/api/operations/acknowledgements")
    def operations_acknowledgements() -> list[dict[str, Any]]:
        """返回最近人工确认和处置记录。"""
        return list_operations_ack(api_service.paths.system_state_path)

    @app.post("/api/operations/acknowledgements")
    def create_operations_acknowledgement(payload: dict[str, Any]) -> dict[str, Any]:
        """记录一次人工确认或处置动作。"""
        try:
            return record_operations_ack(api_service.paths.system_state_path, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/operations/review")
    def operations_review() -> dict[str, Any]:
        """返回运维告警和人工确认的闭环复盘指标。"""
        return build_operations_review(
            api_service.paths.root,
            api_service.paths.system_state_path,
            api_service.readiness(),
        )

    @app.post("/api/operations/quality-report")
    def operations_quality_report(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """生成并登记运维质量趋势报告。"""
        data = payload or {}
        return build_operations_quality_report(
            api_service.paths,
            api_service.readiness(),
            trade_date=str(data.get("trade_date") or "") or None,
        )

    @app.get("/api/logs")
    def logs() -> list[dict[str, Any]]:
        """返回运行日志索引。"""
        return api_service.logs()

    @app.get("/api/logs/{log_id}")
    def log_content(log_id: str) -> dict[str, Any]:
        """返回运行日志内容。"""
        content = api_service.log_content(log_id)
        if content is None:
            raise HTTPException(status_code=404, detail="log not found")
        return content

    @app.get("/api/research/todos")
    def research_todos() -> dict[str, Any]:
        """返回研究待办资料库。"""
        return api_service.research_todos()

    @app.get("/api/research/factor-ideas")
    def factor_ideas() -> list[dict[str, Any]]:
        """返回外部因子想法列表。"""
        return api_service.factor_ideas()

    @app.post("/api/research/factor-ideas")
    def save_factor_idea(payload: dict[str, Any]) -> dict[str, Any]:
        """保存外部因子想法。"""
        try:
            return api_service.save_factor_idea(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/research/strategy-ideas")
    def strategy_ideas() -> list[dict[str, Any]]:
        """返回外部策略想法列表。"""
        return api_service.strategy_ideas()

    @app.post("/api/research/strategy-ideas")
    def save_strategy_idea(payload: dict[str, Any]) -> dict[str, Any]:
        """保存外部策略想法。"""
        try:
            return api_service.save_strategy_idea(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/research/notes")
    def research_notes(note_type: str | None = None) -> list[dict[str, Any]]:
        """返回通用投研记录列表。"""
        return api_service.research_notes(note_type=note_type)

    @app.get("/api/research/notes/{note_id}")
    def research_note_detail(note_id: str) -> dict[str, Any]:
        """返回单条投研记录详情。"""
        detail = api_service.research_note_detail(note_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="research note not found")
        return detail

    @app.post("/api/research/notes")
    def save_research_note(payload: dict[str, Any]) -> dict[str, Any]:
        """保存通用投研记录。"""
        try:
            return api_service.save_research_note(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/research/opportunities")
    def opportunity_themes() -> list[dict[str, Any]]:
        """返回产业机会观察池。"""
        return api_service.opportunity_themes()

    @app.get("/api/research/opportunity-rankings")
    def opportunity_rankings() -> list[dict[str, Any]]:
        """返回最近一次产业方向强势排行。"""
        return api_service.opportunity_rankings()

    @app.post("/api/research/opportunities")
    def save_opportunity_theme(payload: dict[str, Any]) -> dict[str, Any]:
        """保存产业机会观察主题。"""
        try:
            return api_service.save_opportunity_theme(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/research/opportunity-stocks")
    def save_opportunity_stock(payload: dict[str, Any]) -> dict[str, Any]:
        """保存机会主题候选股。"""
        try:
            return api_service.save_opportunity_stock(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/strategy-templates")
    def strategy_templates() -> list[dict[str, Any]]:
        """返回可实例化策略模板。"""
        return api_service.strategy_templates()

    @app.get("/api/strategy-instances")
    def strategy_instances(enabled_only: bool = False) -> list[dict[str, Any]]:
        """返回策略实例列表。"""
        return api_service.strategy_instances(enabled_only=enabled_only)

    @app.post("/api/strategy-instances")
    def save_strategy_instance(payload: dict[str, Any]) -> dict[str, Any]:
        """保存策略实例。"""
        try:
            return api_service.save_strategy_instance(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/strategy-instances/{strategy_id}/state")
    def strategy_instance_state(strategy_id: str) -> dict[str, Any]:
        """返回策略实例最近一次 paper 状态。"""
        return api_service.strategy_instance_state(strategy_id)

    @app.get("/api/accounts/{strategy_id}")
    def account_snapshot(strategy_id: str) -> dict[str, Any]:
        """返回统一账户快照和漂移明细。"""
        snapshot = api_service.account_snapshot(strategy_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="account snapshot not found")
        return snapshot

    @app.post("/api/manual-orders/from-account/{strategy_id}")
    def create_manual_orders_from_account(strategy_id: str) -> dict[str, Any]:
        """从账户快照生成手工调仓单。"""
        try:
            return api_service.create_manual_orders_from_account(strategy_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="account snapshot not found") from exc

    @app.get("/api/manual-orders/{strategy_id}")
    def manual_order_batch(strategy_id: str) -> dict[str, Any]:
        """读取某策略最近一批手工调仓单。"""
        batch = api_service.manual_order_batch(strategy_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="manual order batch not found")
        return batch

    @app.post("/api/manual-orders/batches/{batch_id}/confirm")
    def confirm_manual_order_batch(batch_id: str) -> dict[str, Any]:
        """确认手工调仓批次。"""
        try:
            return api_service.confirm_manual_order_batch(batch_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/manual-orders/orders/{order_id}/fill")
    def fill_manual_order(order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """回填手工成交。"""
        try:
            return api_service.fill_manual_order(order_id, payload)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/manual-orders/orders/{order_id}/reject")
    def reject_manual_order(order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """回填手工拒绝或未成交。"""
        try:
            return api_service.reject_manual_order(order_id, payload)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/strategy-instances/{strategy_id}/transition")
    def transition_strategy_instance(strategy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """按生命周期状态机流转策略实例。"""
        try:
            return api_service.transition_strategy_instance(strategy_id, payload)
        except (ValueError, RuntimeError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.post("/api/factors")
    def save_factor(payload: dict[str, Any]) -> dict[str, Any]:
        """保存正式因子定义。"""
        try:
            return api_service.save_factor(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/factors/{factor_id}")
    def factor_detail(factor_id: str) -> dict[str, Any]:
        """返回因子定义和使用该因子的策略。"""
        detail = api_service.factor_detail(factor_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="factor not found")
        return detail

    @app.get("/api/factor-contracts")
    def factor_contracts() -> list[dict[str, Any]]:
        """返回因子 V2 契约列表。"""
        return api_service.factor_contracts()

    @app.get("/api/factor-contracts/{factor_id}")
    def factor_contract_detail(factor_id: str) -> dict[str, Any]:
        """返回单个因子 V2 契约。"""
        detail = api_service.factor_contract_detail(factor_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="factor contract not found")
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

    @app.post("/api/data/catalog/refresh")
    def refresh_data_catalog(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """刷新本地数据资产目录。"""
        return api_service.refresh_data_catalog(payload or {})

    @app.get("/api/data/sources")
    def data_sources() -> list[dict[str, Any]]:
        """返回已登记的数据源目录。"""
        return api_service.data_sources()

    @app.get("/api/data/sources/{dataset_id}")
    def data_source_detail(dataset_id: str) -> dict[str, Any]:
        """返回单个数据源表结构。"""
        detail = api_service.data_source_detail(dataset_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="data source not found")
        return detail

    @app.post("/api/data/quality-gate")
    def data_quality_gate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """手动执行数据质量门禁。"""
        return api_service.run_data_quality_gate(payload or {})

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
