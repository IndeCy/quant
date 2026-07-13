from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_quality_report_api_generates_indexed_report(tmp_path) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.post("/api/operations/quality-report", json={"trade_date": "20260703"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "20260703"
    assert client.get("/api/reports").json()[0]["report_type"] == "operations_quality_review"
