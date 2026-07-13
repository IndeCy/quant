from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_environment_audit_api_does_not_expose_secret_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "secret-token")
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.get("/api/environment/audit")

    assert response.status_code == 200
    payload = response.json()
    assert "secret-token" not in str(payload)
    assert "checks" in payload
