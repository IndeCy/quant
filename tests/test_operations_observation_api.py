from pathlib import Path

from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_observation_api_returns_latest_run_summary(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    run_dir = paths.runs_dir / "20260702"
    run_dir.mkdir(parents=True)
    for name in ["daily_report.md", "strategy_metrics.json", "portfolio_snapshot.csv", "rebalance_plan.csv", "run_log.txt"]:
        (run_dir / name).write_text("ok", encoding="utf-8")
    pre_market_dir = paths.runs_dir / "20260703"
    pre_market_dir.mkdir()
    (pre_market_dir / "pre_market_check.md").write_text("pre", encoding="utf-8")

    client = TestClient(create_app(LocalApiService(paths)))
    response = client.get("/api/operations/observation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_activity_date"] == "20260703"
    assert payload["latest_activity_type"] == "pre_market_only"
    assert payload["latest_run_date"] == "20260702"
    assert payload["ready_for_daily_review"] is True
    assert payload["run_artifacts"]["daily_report.md"] == "PASS"
