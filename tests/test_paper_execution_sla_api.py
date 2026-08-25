"""Paper执行SLA API测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paper_execution_sla_repository import PaperExecutionSlaRepository
from runtime.paths import RuntimePaths
from runtime.strategy_paper_observation import (
    StrategyPaperObservation,
    StrategyPaperObservationRepository,
)


def test_api_exposes_persisted_sla_progress(tmp_path) -> None:
    """调度页只能通过API读取账本，不扫描运行目录。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    repository = PaperExecutionSlaRepository(paths.system_state_path)
    repository.record(
        {
            "trade_date": "20260724",
            "status": "SUCCESS",
            "run_status": "NO_ACTION",
            "due_orders": 0,
            "filled_orders": 0,
            "rejected_orders": 0,
            "cancelled_orders": 0,
            "pending_orders": 0,
            "late_orders": 0,
            "issues": [],
        }
    )

    response = TestClient(
        create_app(LocalApiService(paths))
    ).get("/api/scheduler/paper-execution-sla")

    assert response.status_code == 200
    payload = response.json()
    assert payload["progress"]["current_streak"] == 1
    assert payload["progress"]["remaining_days"] == 19
    assert payload["history"][0]["trade_date"] == "20260724"


def test_api_exposes_strategy_isolated_observation_progress(tmp_path) -> None:
    """长期Paper候选必须显示自己的20日进度，不能借用平台总SLA。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    service = LocalApiService(paths)
    service.system_repository.upsert_strategy_instance(
        {
            "strategy_id": "candidate",
            "name": "候选策略",
            "template_id": "factor_topn_monthly",
            "status": "paper",
            "enabled": True,
            "universe": "all_a",
            "filters": [],
            "factors": [],
            "construction": {"top_n": 20},
            "risk_overlay": "none",
            "benchmark": "510300",
            "config": {"paper_observation_gate_days": 20},
        }
    )
    repository = StrategyPaperObservationRepository(paths.system_state_path)
    repository.record(
        StrategyPaperObservation(
            "candidate", "20260724", "SUCCESS", "SUCCESS", "NO_ACTION",
            0, 0, 0, 0, 0, 0, (),
        )
    )

    payload = TestClient(create_app(service)).get(
        "/api/scheduler/paper-execution-sla"
    ).json()

    assert payload["strategies"][0]["strategy_id"] == "candidate"
    assert payload["strategies"][0]["progress"]["current_streak"] == 1
