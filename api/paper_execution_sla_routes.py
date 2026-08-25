"""Paper执行SLA路由。"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import FastAPI


class PaperExecutionSlaService(Protocol):
    """路由依赖的最小查询契约。"""

    def paper_execution_sla(self) -> dict[str, Any]: ...


def register_paper_execution_sla_routes(
    app: FastAPI,
    service: PaperExecutionSlaService,
) -> None:
    """登记只读SLA进度接口。"""

    @app.get("/api/scheduler/paper-execution-sla")
    def paper_execution_sla() -> dict[str, Any]:
        return service.paper_execution_sla()
