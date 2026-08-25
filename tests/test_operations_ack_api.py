from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_ack_api_records_and_lists_acknowledgement(tmp_path) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.post(
        "/api/operations/acknowledgements",
        json={
            "trade_date": "20260703",
            "source": "operations_observation",
            "category": "scheduler",
            "name": "heartbeat",
            "severity": "WARNING",
            "decision": "ACTION_REQUIRED",
            "message": "heartbeat 状态为 WARN",
            "resolution": "已确认 scheduler 正常运行",
            "operator": "admin",
        },
    )

    assert response.status_code == 200
    records = client.get("/api/operations/acknowledgements").json()
    assert records[0]["name"] == "heartbeat"
    assert records[0]["status"] == "ACKNOWLEDGED"
