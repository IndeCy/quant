"""风险恢复相关本地 API 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from api.service import LocalApiService
from runtime.risk_confirmation import build_risk_confirmation_state
from runtime.risk_recovery_service import confirm_risk_recovery


def register_risk_recovery_routes(app: FastAPI, service: LocalApiService) -> None:
    """注册风险恢复人工确认接口，保持主 API 入口文件规模可控。"""

    @app.post("/api/risk-recoveries/{recommendation_id}")
    def confirm_strategy_risk_recovery(recommendation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """批准分级恢复或继续限仓，并返回最新风险状态。"""
        try:
            result = confirm_risk_recovery(
                service.paths,
                recommendation_id,
                str(payload.get("decision") or ""),
            )
            state = build_risk_confirmation_state(service.paths)
            state["recovery_execution"] = result
            return state
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
