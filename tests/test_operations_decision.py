from pathlib import Path

from runtime.operations_decision import build_operations_decision


def _seed_complete_run(root: Path) -> None:
    run_dir = root / "runs" / "20260702"
    run_dir.mkdir(parents=True)
    for name in ["daily_report.md", "strategy_metrics.json", "portfolio_snapshot.csv", "rebalance_plan.csv", "run_log.txt"]:
        (run_dir / name).write_text("ok", encoding="utf-8")
    (root / "state").mkdir()
    (root / "state" / "scheduler.heartbeat").write_text("ok", encoding="utf-8")
    (root / "state" / "scheduler.sqlite").write_text("", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "scheduler.log").write_text("ok", encoding="utf-8")
    (root / "reports").mkdir()
    for name in ["dashboard.html", "dashboard_data.json", "quality_overlay_paper_latest.md"]:
        (root / "reports" / name).write_text("ok", encoding="utf-8")


def test_operations_decision_reports_no_action_when_all_inputs_pass(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BARK_URL", "https://api.day.app/key")
    _seed_complete_run(tmp_path)
    readiness = {"status": "READY", "checks": [{"name": "scheduler_job", "status": "PASS", "message": "ok"}]}

    decision = build_operations_decision(tmp_path, readiness)

    assert decision["decision"] == "NO_ACTION"
    assert decision["severity"] == "NORMAL"
    assert decision["manual_intervention_required"] is False
    assert decision["latest_run_date"] == "20260702"
    assert decision["actions"] == []


def test_operations_decision_requires_action_for_failures(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BARK_URL", raising=False)
    (tmp_path / "runs" / "20260703").mkdir(parents=True)
    readiness = {"status": "NOT_READY", "checks": [{"name": "scheduler_job", "status": "FAIL", "message": "每日任务未登记"}]}

    decision = build_operations_decision(tmp_path, readiness)

    assert decision["decision"] == "ACTION_REQUIRED"
    assert decision["severity"] == "CRITICAL"
    assert decision["manual_intervention_required"] is True
    assert any(action["source"] == "readiness" for action in decision["actions"])
    assert any(action["source"] == "operations_observation" for action in decision["actions"])
