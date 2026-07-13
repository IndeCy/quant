"""正式因子登记 API 测试。"""

from pathlib import Path

from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_catalog import register_quality_alpha_v1


def test_local_api_service_saves_factor_definition(tmp_path: Path) -> None:
    """外部因子经过人工结构化后，应能沉淀到正式因子库。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    saved = service.save_factor(_factor_payload())

    assert saved["factor_id"] == "profit_stability"
    assert service.factor_detail("profit_stability")["config"]["as_of_field"] == "f_ann_date"
    assert "profit_stability" in [item["factor_id"] for item in service.factors()]


def test_fastapi_saves_factor_definition(tmp_path: Path) -> None:
    """前端应能通过 POST /api/factors 保存正式因子定义。"""
    service = LocalApiService(_seed_runtime(tmp_path))
    client = TestClient(create_app(service))

    response = client.post("/api/factors", json=_factor_payload())

    assert response.status_code == 200
    assert client.get("/api/factors/profit_stability").json()["name"] == "盈利稳定性"


def _seed_runtime(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    register_quality_alpha_v1(SystemRepository(paths.system_state_path))
    return paths


def _factor_payload() -> dict[str, object]:
    return {
        "factor_id": "profit_stability",
        "name": "盈利稳定性",
        "category": "quality",
        "direction": "lower_is_better",
        "source": "manual",
        "description": "过去三年ROA波动率越低越好",
        "config": {"as_of_field": "f_ann_date"},
    }
