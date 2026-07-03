from pathlib import Path

from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_decision_api_returns_actionable_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BARK_URL", "https://api.day.app/key")
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    run_dir = paths.runs_dir / "20260702"
    run_dir.mkdir(parents=True)
    for name in ["daily_report.md", "strategy_metrics.json", "portfolio_snapshot.csv", "rebalance_plan.csv", "run_log.txt"]:
        (run_dir / name).write_text("ok", encoding="utf-8")

    client = TestClient(create_app(LocalApiService(paths)))
    response = client.get("/api/operations/decision")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] in {"NO_ACTION", "ACTION_REQUIRED"}
    assert "manual_intervention_required" in payload
    assert "actions" in payload
