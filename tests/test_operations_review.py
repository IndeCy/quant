from pathlib import Path

from runtime.operations_ack import record_operations_ack
from runtime.operations_review import build_operations_review


def _seed_warning(root: Path) -> None:
    (root / "runs" / "20260703").mkdir(parents=True)


def test_operations_review_marks_open_when_actions_have_no_ack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BARK_URL", raising=False)
    _seed_warning(tmp_path)
    db_path = tmp_path / "state" / "system_state.sqlite"
    readiness = {"status": "READY", "checks": []}

    review = build_operations_review(tmp_path, db_path, readiness)

    assert review["closure_status"] == "OPEN"
    assert review["current_action_count"] > 0
    assert review["unacknowledged_action_count"] > 0
    assert review["acknowledged_action_count"] == 0


def test_operations_review_counts_matching_acknowledgement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BARK_URL", raising=False)
    _seed_warning(tmp_path)
    db_path = tmp_path / "state" / "system_state.sqlite"
    record_operations_ack(
        db_path,
        {
            "trade_date": "20260703",
            "source": "operations_observation",
            "category": "run_artifacts",
            "name": "daily_report.md",
            "severity": "WARNING",
            "decision": "ACTION_REQUIRED",
            "message": "run_artifacts.daily_report.md 状态为 WARN",
            "resolution": "已确认盘前活动不需要日报",
            "operator": "admin",
        },
    )
    readiness = {"status": "READY", "checks": []}

    review = build_operations_review(tmp_path, db_path, readiness)

    assert review["closure_status"] == "OPEN"
    assert review["acknowledged_action_count"] == 1
    assert review["unacknowledged_action_count"] >= 1
