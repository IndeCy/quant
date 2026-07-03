from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_review_api_returns_closure_metrics(tmp_path) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.get("/api/operations/review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["closure_status"] in {"OPEN", "CLOSED"}
    assert "current_action_count" in payload
    assert "acknowledgement_count" in payload
